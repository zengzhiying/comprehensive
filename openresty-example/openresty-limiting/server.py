#!/usr/bin/env python3
# coding=utf-8
import time

from gevent import monkey; monkey.patch_all()
from bottle import route, run, template

@route('/hello/<name>')
def index(name):
    time.sleep(2)
    return template('<p>Hello {{name}}</p>', name=name)

run(server='gevent',host='127.0.0.1', port=8088)
