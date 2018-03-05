# coding=utf-8
import time

import requests
from bs4 import BeautifulSoup

class Crawl(object):
    """搜狗微信抓取工具类
    包括登录, 抓取页面文章列表, 抓取文章内容等.
    """
    def __init__(self):
        # 请求头
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, sdch',
            'Accept-Language': 'zh-CN,zh;q=0.8,en;q=0.6',
            'Connection': 'keep-alive',
            'Host': 'weixin.sogou.com',
            'Referer': 'http://weixin.sogou.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'
        }
        self.weixin_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
            'Host': 'mp.weixin.qq.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'
        }
        self.session = requests.Session()


    def init_cookies(self):
        """初始化cookie登录
        加载已经登录产生的cookie文件, 后续请求页面均携带cookie进行请求
        初始化时执行一次即可.
        cookie完整内容可以在页面按F12切换至console执行: document.cookie
        然后将返回内容复制并保存至文件即可.
        """
        with open('cookies.txt', 'r') as f:
            cookie_content = f.read().strip()
        cks = cookie_content.split('; ')
        self.cookies = {}
        for c in cks:
            k, v = c.split('=')
            self.cookies[k] = v
        print('load cookie done. {}'.format(self.cookies))

    def get_page_articles(self, page_uri):
        """获取页面文章列表
        Args: 
            page_uri: 文章列表页地址(直接带参数即可)
        Returns:
            解析成功返回文章列表, 类型: list 如下:
            [
            {'title': '标题名',
            'summary': '摘要',
            'article_uri': '文章链接',
            'account_name': '公众号账户名'
            },
            {},
            ...
            ]
            解析失败返回: None
        """
        try:
            start_time = time.time()
            r = requests.get(page_uri,
                             headers=self.headers,
                             cookies=self.cookies,
                             timeout=10)
            end_time = time.time()
        except requests.exceptions.RequestException as e:
            print("http请求异常！error: {}".format(e))
            return None
        else:
            if r.status_code != 200:
                print("http状态码错误！code: %d" % r.status_code)
                return None
            print("http请求成功. length: {} 耗时: {}s".format(len(r.text), end_time - start_time))
            # 解析
            articles = self.__article_list_analyze(r.text)
            return articles

    def __article_list_analyze(self, html):
        """文章列表页解析
        Args: 
            html: html页面源代码
        Returns:
            解析成功返回列表, 格式和主调用方法一致
            解析失败返回None
        """
        bsoup = BeautifulSoup(html, "html.parser")
        boxs = bsoup.find_all('div', class_='txt-box')
        if not boxs:
            # 没有匹配到
            return None
        print("box number: {}".format(len(boxs)))
        articles = []
        for box in boxs:
            items = {
                'title': '',
                'summary': '',
                'article_uri': '',
                'account_name': ''
            }
            if box.h3.a.contents:
                items['title'] = box.h3.a.get_text()
            if box.h3.a.attrs and 'href' in box.h3.a.attrs:
                items['article_uri'] = box.h3.a.attrs['href']
            if box.p:
                items['summary'] = box.p.get_text()
            account_search = box.find_all('div', class_='s-p')
            # box.div.a
            if account_search:
                items['account_name'] = account_search[0].a.get_text()
            articles.append(items)
        return articles

    def get_article(self, page_uri):
        """抓取微信文章页面内容
        Args: 
            page_uri:  微信文章页链接
        Returns:
            抓取成功返回页面内容, 类型: dict 如下:
            {"title": "文章标题",
            "date": "发布日期",
            "account_name": "公众号名称",
            "account_number": "微信账号",
            "features": "功能介绍.",
            "text_contents": "正文内容."}
            抓取失败返回None
        """
        try:
            start_time = time.time()
            r = self.session.get(page_uri,
                                 headers=self.weixin_headers,
                                 timeout=10)
            end_time = time.time()
        except requests.exceptions.RequestException as e:
            print("http请求异常！error: {}".format(e))
            return None
        else:
            if r.status_code != 200:
                print("http状态码错误！code: %d" % r.status_code)
                return None
            print("http请求成功. length: {} 耗时: {}s".format(len(r.text), end_time - start_time))
            # 解析
            articles = self.__article_details_analyze(r.text)
            return articles

    def __article_details_analyze(self, html):
        """微信文章详情页内容分析
        """
        bsoup = BeautifulSoup(html, "html.parser")
        details = {
            'title': '',
            'date': '',
            'account_name': '',
            'account_number': '',
            'features': '',
            'text_contents': ''
        }
        title_tag = bsoup.find_all(id='activity-name')
        if title_tag:
            details['title'] = title_tag[0].get_text().strip()
        date_tag = bsoup.find(id='post-date')
        if date_tag:
            details['date'] = date_tag.get_text()
        introduction_tag = bsoup.find(id='js_profile_qrcode')
        if introduction_tag:
            account_name_tag = introduction_tag.find(class_='profile_nickname')
            if account_name_tag:
                details['account_name'] = account_name_tag.get_text()
            features_tag = introduction_tag.find_all(class_='profile_meta_value')
            if features_tag and len(features_tag) == 2:
                details['account_number'] = features_tag[0].get_text()
                details['features'] = features_tag[1].get_text()
        content_tag = bsoup.find(id='js_content')
        if content_tag:
            details['text_contents'] = content_tag.get_text().strip().replace('\xa0', ' ')
        else:
            print("文章内容为空！不保存. ")
            return None
        return details
