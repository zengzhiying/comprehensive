#!/usr/bin/python3
# coding=utf-8
"""搜狗微信文章搜索页抓取任务执行脚本
"""
import os
import time
import random
import pickle
from urllib import parse

from crawl import Crawl

def save_article(details):
    """保存微信详细文章内容到文件
    每篇文章一个文件, 文件名: 时间戳.dat
    存储格式: c序列化
    """
    article_dir = "./articles"
    article_filename = '{}.dat'.format(int(time.time()))
    with open(os.path.join(article_dir, article_filename), 'wb') as f:
        pickle.dump(details, f)
    print("saved file: {}".format(article_filename))

def save_break_point(filename, page_number, article_number):
    """保存断点文件.
    """
    with open(filename, 'w') as f:
        f.write('{} {}'.format(page_number, article_number))
        f.flush()

def get_break_point(filename):
    """获取断点值
    """
    f = open(filename, 'r')
    v = f.read()
    f.close()
    return [int(x) for x in v.split(' ')]

if __name__ == '__main__':
    key_word = "智慧图书馆"
    craw = Crawl()
    craw.init_cookies()
    page_number = 1  # 起始抓取页数
    article_number = 0  # 处理文章数量
    break_point_filename = "./break_point.dat"
    if os.path.isfile(break_point_filename):
        page_number, article_number = get_break_point(break_point_filename)
    # 保存文章列表文件名
    articles_filename = "articles.csv"
    if not os.path.isfile(articles_filename):
        # 文件不存在, 创建新模板
        print("初始化模板文件.")
        fp = open(articles_filename, 'w')
        fp.write('title;summary;article_uri;account_name\n')
        fp.close()
    with open(articles_filename, 'a') as fp:
        while True:
            page_uri = "http://weixin.sogou.com/weixin?query={}&_sug_type_=&s_from=input&_sug_=n&type=2&page={}&ie=utf8".format(parse.quote(key_word), page_number)  
            articles = craw.get_page_articles(page_uri)
            if not articles:
                print("当前抓取到列表为空！当前处理页数: {} 当前处理文章总数: {}, 请检查原因后继续运行.".format(page_number, article_number))
                break
            # 抓取成功, 存储
            for item in articles:
                write_line = "{};{};{};{}\n".format(item['title'],
                                                    item['summary'],
                                                    item['article_uri'],
                                                    item['account_name'])
                fp.write(write_line)
                if item['article_uri'] == '':
                    print("文章uri 为空！")
                    break
                article_detail = craw.get_article(item['article_uri'])
                if article_detail is None:
                    print("抓取文章失败！")
                    break
                # 成功. 保存文件
                save_article(article_detail)
                article_number += 1
                time.sleep(2)
            fp.flush()
            print("刷盘成功! 页数: {} 处理条数: {}".format(page_number, article_number))
            page_number += 1
            # 保存断点
            save_break_point(break_point_filename, page_number, article_number)
            wait_interval = random.randint(1, 5)
            print("Waiting for the interval: {}s".format(wait_interval))
            time.sleep(wait_interval)

        print("close file.")
        fp.flush()
