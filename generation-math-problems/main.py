import random
import math
from PIL import Image, ImageDraw, ImageFont


# ==========================
# 配置
# ==========================

IMAGE_WIDTH = 2480      # A4 300DPI
IMAGE_HEIGHT = 3508

MARGIN_X = 120          # 左右页边距
MARGIN_BOTTOM = 140     # 底部页边距

TITLE_SIZE = 108        # 标题字号
TITLE_TOP = 110         # 标题距纸张顶部
NAME_SIZE = 44          # 姓名/日期行字号
HEADER_GAP = 70         # 标题、姓名行、题目区之间的间距

MAX_FONT_SIZE = 96      # 题目字号上限（保持在标题之下）
REF_SIZE = 40           # 估算文本宽度用的参考字号

MAX_COLUMNS = 6         # 最多分几列
COL_GAP_RATIO = 0.12    # 列间留白占列宽的比例
MIN_LINE_RATIO = 1.6    # 行距至少为字号的多少倍
MAX_LINE_RATIO = 3.2    # 行距至多为字号的多少倍，超过会显得版面稀疏
MIN_FILL_WIDTH = 0.70   # 最长题目至少要占列宽的比例，否则会缩在纸张左半边

TITLE = "100以内加减法练习"


# ==========================
# 字体
# ==========================

def load_font(size):
    # (字体路径, ttc 子字体索引)；index 对 .ttf 无影响
    candidates = [
        # Linux（Noto CJK 集合中 index=2 为简体中文 SC）
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 2),
        # macOS
        ("/System/Library/Fonts/PingFang.ttc", 0),
        # Windows
        ("msyh.ttc", 0),
        ("simhei.ttf", 0),
        ("simsun.ttc", 0),
    ]

    for path, index in candidates:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            pass

    print("警告：未找到中文字体，汉字将显示为方框")
    return ImageFont.load_default()


title_font = load_font(TITLE_SIZE)
name_font = load_font(NAME_SIZE)


# ==========================
# 生成题目
# ==========================

def build_problem_pool():
    """枚举全部合法算式，同一道题只保留一条。

    加法交换律下 a+b 与 b+a 是同一道题，按 a<=b 去重（书写顺序在抽题时随机决定）；
    减法 a-b 与 b-a 结果不同，属于两道题，各自保留。
    """

    pool = []

    # 加法：和不超过 100，两个加数不能同时为 0
    for a in range(0, 51):
        for b in range(a, 101 - a):
            if a == 0 and b == 0:
                continue
            pool.append(("+", a, b))

    # 减法：被减数至少为 1，减数在 1~被减数之间（结果非负且不出现「减 0」）
    for a in range(1, 101):
        for b in range(1, a + 1):
            pool.append(("-", a, b))

    return pool


def draw_problems(count):
    """从题库中不重复地抽取 count 道题，返回排版用的文本列表。"""

    pool = build_problem_pool()

    if count > len(pool):
        raise ValueError(f"题目数量超出题库容量（最多 {len(pool)} 题）")

    texts = []

    # sample 为无放回抽样，保证同一份试卷里不会出现重复的题
    for op, a, b in random.sample(pool, count):
        if op == "+" and random.random() < 0.5:
            a, b = b, a     # 随机书写顺序，避免加法的题面清一色小数在前
        texts.append(f"{a:>2} {op} {b:>2} = ______")

    return texts


# ==========================
# 版面计算
# ==========================

def content_top():
    """题目区顶部 y 坐标（扣掉标题和姓名行占的高度）。"""

    return TITLE_TOP + TITLE_SIZE + HEADER_GAP + NAME_SIZE + HEADER_GAP


def choose_layout(texts):
    """挑选列数，让字号尽可能大、同时铺满纸张。

    列数越多，每列越窄、字号越小，但行数越少、行距越松；列数越少则相反。
    这里枚举所有列数，在"横向铺得满、纵向不稀疏"的布局里取字号最大者。
    """

    area_w = IMAGE_WIDTH - 2 * MARGIN_X
    area_h = IMAGE_HEIGHT - MARGIN_BOTTOM - content_top()

    ref = load_font(REF_SIZE)
    longest = max(ref.getlength(t) for t in texts)

    candidates = []

    for columns in range(1, MAX_COLUMNS + 1):

        rows = math.ceil(len(texts) / columns)
        col_w = area_w / columns
        line_h = area_h / rows

        # 字号的两个上限：列宽要放得下最长的一道题，
        # 行高要不小于 MIN_LINE_RATIO 倍字号（否则行与行会挤在一起）
        by_width = col_w * (1 - COL_GAP_RATIO) * REF_SIZE / longest
        by_height = line_h / MIN_LINE_RATIO
        size = int(min(by_width, by_height, MAX_FONT_SIZE))

        fill = longest * size / REF_SIZE / col_w    # 最长题目占列宽的比例
        ratio = line_h / size                       # 行距是字号的多少倍

        # 题量少时行数少，行距会被撑得很大：宁可多分几列让版面紧凑
        if fill >= MIN_FILL_WIDTH and ratio <= MAX_LINE_RATIO:
            candidates.append((size, columns, rows))

    if not candidates:      # 兜底：没有合格布局时退回字号最大的那个
        for columns in range(1, MAX_COLUMNS + 1):
            rows = math.ceil(len(texts) / columns)
            size = int(min(area_w / columns * (1 - COL_GAP_RATIO) * REF_SIZE / longest,
                           area_h / rows / MIN_LINE_RATIO,
                           MAX_FONT_SIZE))
            candidates.append((size, columns, rows))

    size, columns, rows = max(candidates, key=lambda c: c[0])

    # 上面的字号是按比例估算的，按所选字号实测一次，超宽就回退
    limit = area_w / columns * (1 - COL_GAP_RATIO)
    font = load_font(size)
    width = max(font.getlength(t) for t in texts)

    if width > limit:
        size = max(1, int(size * limit / width))
        font = load_font(size)

    return font, size, columns, rows


# ==========================
# 生成试卷
# ==========================

def generate_exam(count, output, numbered=False):

    if count < 20 or count > 100:
        raise ValueError("题目数量必须在20~100之间")

    texts = draw_problems(count)

    if numbered:
        texts = [f"{i + 1}. {t}" for i, t in enumerate(texts)]

    img = Image.new(
        "RGB",
        (IMAGE_WIDTH, IMAGE_HEIGHT),
        "white"
    )

    draw = ImageDraw.Draw(img)

    # 标题
    draw.text(
        (IMAGE_WIDTH // 2, TITLE_TOP + TITLE_SIZE / 2),
        TITLE,
        fill="black",
        font=title_font,
        anchor="mm"
    )

    # 姓名 / 日期 / 得分，三段横向铺开
    name_y = TITLE_TOP + TITLE_SIZE + HEADER_GAP

    draw.text(
        (MARGIN_X, name_y),
        "姓名：______________",
        fill="black",
        font=name_font,
        anchor="la"
    )

    draw.text(
        (IMAGE_WIDTH * 0.42, name_y),
        "日期：______________",
        fill="black",
        font=name_font,
        anchor="la"
    )

    draw.text(
        (IMAGE_WIDTH - MARGIN_X, name_y),
        "得分：__________",
        fill="black",
        font=name_font,
        anchor="ra"
    )

    # 题目区：行高按可用高度均分，题目在行内垂直居中
    font, size, columns, rows = choose_layout(texts)

    area_w = IMAGE_WIDTH - 2 * MARGIN_X
    area_h = IMAGE_HEIGHT - MARGIN_BOTTOM - content_top()

    col_w = area_w / columns
    line_h = area_h / rows
    top = content_top()

    for i, text in enumerate(texts):

        row = i % rows
        col = i // rows

        x = MARGIN_X + col * col_w + col_w * COL_GAP_RATIO / 2
        y = top + row * line_h + line_h / 2

        draw.text(
            (x, y),
            text,
            fill="black",
            font=font,
            anchor="lm"
        )

    img.save(output)
    print(f"已生成：{output}（{count} 题，{columns} 列 × {rows} 行，字号 {size}px）")


# ==========================
# 主程序
# ==========================

if __name__ == "__main__":

    while True:
        try:
            count = int(input("请输入题目数量(20~100)："))

            if 20 <= count <= 100:
                break

            print("请输入20~100之间的数字")

        except:
            print("输入错误")

    try:
        numbered = input("是否添加题号？(y/N)：").strip().lower() in ("y", "yes", "是")
    except EOFError:        # 输入被管道关闭时按默认处理
        numbered = False

    generate_exam(count, "exercise.png", numbered)
