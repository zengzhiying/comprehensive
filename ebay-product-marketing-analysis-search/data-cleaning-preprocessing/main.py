#!/usr/bin/env python3
# coding=utf-8
import pandas as pd
import numpy as np

if __name__ == '__main__':
    df = pd.read_csv('marketing_sample_for_ebay_com-ebay_com_product__20210101_20210331__30k_data.csv', encoding_errors='ignore', on_bad_lines='warn')
    # df.info()
    # print(df.count())

    selected_columns = ['Uniq Id', 'Crawl Timestamp', 'Pageurl', 'Website', 'Title', 'Model Num', 'Manufacturer', 'Model Name', 'Price', 
        'Stock', 'Carrier', 'Color Category', 'Internal Memory', 'Screen Size', 'Five Star', 'Four Star', 'Three Star',
        'Two Star', 'One Star', 'Discontinued', 'Broken Link', 'Seller Rating', 'Seller Num Of Reviews']

    df = df[selected_columns]
    # print(df.head(10).to_dict(orient='records'))

    rename_columns = []
    for col in selected_columns:
        lower_column = col.lower()
        new_column = lower_column.replace(" ", "_")
        rename_columns.append(new_column)

    # 字段含义
    # model_num: 型号编号
    # manufacturer: 制造商
    # model_name: 型号名称
    # price: 价格
    # stock: 库存
    # carrier: 运营商
    # color_category: 颜色分类
    # internal_memory: 内存
    # screen_size: 屏幕尺寸
    # five_star: 5星数量
    # four_star: 4星数量
    # three_star: 3星数量
    # two_star: 2星数量
    # one_star: 1星数量
    # discontinued: 是否停产
    # broken_link: 链接是否失效
    # seller_rating: 卖家评分
    # seller_num_of_reviews: 卖家评价数量
    df = df.rename(columns=dict(zip(selected_columns, rename_columns)))
    df = df.rename(columns={'pageurl': 'page_url'})
    
    df = df[df['title'].notna()]
    
    df[['model_num', 'manufacturer', 'model_name', 'carrier', 'color_category', 'internal_memory', 'screen_size']] = df[['model_num','manufacturer','model_name', 'carrier', 'color_category', 'internal_memory', 'screen_size']].fillna('unknown')
    
    # 将 stock 字符串列 TRUE 转为 1, FALSE 转为 0, nan 转为 0
    df['stock'] = df['stock'].map({'TRUE': 1, 'FALSE': 0}).fillna(0).astype(int)
    # 将 discontinued 字符串列 TRUE 转为 1, FALSE 转为 0, nan 转为 0
    df['discontinued'] = df['discontinued'].map({'TRUE': 1, 'FALSE': 0}).fillna(0).astype(int)
    # 将 broken_link 字符串列 TRUE 转为 1, FALSE 转为 0, nan 转为 0
    df['broken_link'] = df['broken_link'].map({'TRUE': 1, 'FALSE': 0}).fillna(0).astype(int)
    
    # 分别进行分组，统计每个分组的数量
    print(df.groupby('stock').size())
    print(df.groupby('discontinued').size())
    print(df.groupby('broken_link').size())
    # 转换 price 列去掉 $ 符号和空格，只保留数字部分，空值使用字符串 '0.0' 填充
    df['price'] = df['price'].str.replace('$', '', regex=False).str.replace(',', '', regex=False).str.strip().fillna('0.0')
    def convert_price(value):
        try:
            float(value)
            return value
        except ValueError:
            return '0.0'
    df['price'] = df['price'].map(convert_price)

    def convert_to_numeric(value):
        if value == 'FALSE':
            return 0
        try:
            return int(value)
        except ValueError:
            return 0

    star_columns = ['five_star', 'four_star', 'three_star', 'two_star', 'one_star']
    df[star_columns] = df[star_columns]\
        .fillna('0').map(convert_to_numeric).astype(int)

    total_reviews = df[star_columns].sum(axis=1)
    weighted_sum = (df['five_star'] * 5 + df['four_star'] * 4 + df['three_star'] * 3 + df['two_star'] * 2 + df['one_star'] * 1)
    df['average_star'] = np.where(total_reviews > 0, weighted_sum / total_reviews, 0)

    df = df.drop(star_columns, axis=1)

    def convert_seller_rating(value):
        if pd.isna(value):
            return 0
        try:
            # 去掉 % 符号并转换为浮点数，再按 10 分制换算
            return float(value.rstrip('%')) / 10
        except ValueError:
            return 0
        
    df['seller_rating'] = df['seller_rating'].apply(convert_seller_rating)

    df['seller_num_of_reviews'] = df['seller_num_of_reviews'].fillna(0).map(convert_to_numeric).astype(int)

    print(df.head(10).to_dict(orient='records'))
    df.info()

    # 计算列的最大长度
    '''
    for column in df.columns:
        max_length = df[column].astype(str).str.len().max()
        #max_idx = df[column].astype(str).str.len().argmax()
        print(f"'{column}' 列的最大长度：", max_length)

    row_lengths = df['seller_rating'].map(lambda x: len('{}'.format(x)))
    max_length_row_index = row_lengths.idxmax()
    max_length_row = df.loc[max_length_row_index]
    print(max_length_row.astype(str).to_json())
    '''
    print(df[['manufacturer']].groupby('manufacturer').size().nlargest(10))
    review_top = df[['uniq_id', 'seller_num_of_reviews']].sort_values(by='seller_num_of_reviews', ascending=False).head(10)
    print(review_top)
    df.to_csv('ebay-product.csv', index=False)
    
