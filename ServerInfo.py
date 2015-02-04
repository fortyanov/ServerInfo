#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'Fedor Ortyanov, Alexey Nabrodov'

from fabric.colors import *
from fabric.contrib.files import *
from fabric.exceptions import *
from bottle import route, debug, template, request, static_file, get
from bottle import run as bottle_run
from bottle import get as bottle_get
import json
import re
import os
import sys
import requests
from datetime import datetime

########## Проверка существования json-а с настройками ##############
if os.path.exists(os.path.join(os.path.dirname(__file__), 'settings.json')):
    #with cd(os.path.join(os.path.dirname(__file__))):
    settings_data = json.load(open('settings.json'))
    settings_servers = settings_data['servers']
    settings_sub_proj = settings_data['sub_projects']
    settings_update = bool(settings_data['need_update'])
else:
    print(red('Settings file not found, you must create it first'))
    sys.exit(1)

def get_supervisor_status():
    """
        Посмотреть статус сервака
    """
    #data = sudo('supervisorctl status', timeout=5).split("\r\n")
    data = sudo('supervisorctl status').split("\r\n")
    for i, line in enumerate(data):
        formatted_data = filter(lambda x: x != '', line.split(" "))                        # рубим строку по пробелам и если пробелов много появляются элементы содержащие '', filter убирает их спомошью лямбда-функции
        res_data = {'proc_name': formatted_data[0], 'proc_status': formatted_data[1]}
        if formatted_data[1] != 'RUNNING':
            res_data['proc_data'] = u'Процесс не запущен'
        else:
            res_data['proc_data'] = ' '.join(formatted_data[2:])
        data[i] = res_data
    return data


def make_update(server_name):
    """
        Обновить изменения в серваках
    """
    try:
        sudo('apt-get update -q')
        sudo('apt-get dist-upgrade -yq')
    except:
        print("Server %s can't update\n" % server_name)


def get_version(subproj):
    """
        Получить версию подпроекта
    """
    distrib_url = "http://172.20.6.20:8111/repository/download/EmercomGenerator_InstallerBuild/latest.lastSuccessful/releases/emercom_3_%slatest.tgz%%21/emercom_3_%slatest/"   # репозиторий содержит установочник с последней актуальной версией
    vp = '/var/www/v3/%s/version.py'                        # содержит версию которая в данный момент на серваке для подпроекта
    vp = vp % (subproj if subproj != "pdg_emercom" else "%s/emercom" % subproj)
    url = distrib_url + ("%s/version.py" % (subproj if subproj != "pdg_emercom" else "%s/emercom" % subproj))
    url %= ('' if subproj != "pdg_emercom" else "generator_", '' if subproj != "pdg_emercom" else "generator_")
    latest_version = requests.get(url, auth=("emercom", "emercom")).text
    version_num = "Ошибка"
    if exists(vp):
        version = run('cat %s' % vp)
        if subproj != "pdg_emercom":
            form_version = re.match("VERSION = \'(.*)\'", version)
            version_num = form_version.groups()[0]
        else:
            for oneStr in version.split('\n'):
                form_version = re.match("#FL_BUILD_NUMBER_STR \"(.+)\"", oneStr)
                if form_version is not None:
                    version_num = form_version.groups()[0]
                    break
    if subproj != "pdg_emercom":
        latest_version = re.match("VERSION = \'(.*)\'", latest_version).groups()[0]
    else:
        for oneStr in latest_version.split('\n'):
            latest_version = re.match("#FL_BUILD_NUMBER_STR \"(.+)\"", oneStr)
            if latest_version is not None:
                latest_version = latest_version.groups()[0]
                break
    return version_num, latest_version


def get_git_status(subproj):
    """
        Получить статус и ревизию из гита для подпроекта
    """
    if exists('/var/www/v3/%s/.git' % subproj):
        with cd('/var/www/v3/%s' % subproj):
            bs = run('git rev-parse --abbrev-ref HEAD')
            rev = run('git rev-parse HEAD')
            com = run('git log --pretty=format:"%s" -1 --no-color')
            git_data = {'branch': bs, 'revision': rev[:11], 'comment': com[7:-15]}
    else:
        git_data = {'branch': None, 'revision': None, 'comment': None}
    return git_data


def sub_projects_data(subprojects):
    """
        Получить информацию о нескольких подпроектах
    """
    res = {}
    for sp in subprojects:
        v = get_version(sp)
        res[sp] = {'version': v[0], 'latest_version': v[1], 'git_data': get_git_status(sp)}
    return res


def get_server_info(server_name, server_user, server_pass,
                    sub_projects=None, need_update=False):
    """
        Собрать необходимую информацию о конкретном сервере
    """
    if sub_projects is None:
        sub_projects = ["emercom", "dev", "api", "pdg_emercom"]
    with settings(user=server_user, password=server_pass, host_string="%s@%s" % (server_user, server_name)):
        try:
            if need_update:
                make_update(server_name)
            sed('/etc/hosts', 'localhost ".*"', 'localhost %s' % server_name, use_sudo=True)        # Прописываем в хостс для каждго сервака имя для локального
            status = get_supervisor_status()
            sub_data = sub_projects_data(sub_projects)
            return {'status': status, 'sub_projects': sub_data}
        except NetworkError:
            print("Can't connect to server %s\n" % server_name)
            return None


def update_servers_info_from_file():
    """
        Пробежаться по всем серверам из ВХОДНОГО ФАЙЛА и собрать инфу по ним
    """
    result = {'servers': {}}
    for server_name in settings_servers:
        server_data = get_server_info(server_name, settings_servers[server_name]['user'], settings_servers[server_name]['password'], settings_sub_proj, settings_update)
        if server_data:
            result['servers'][server_name] = server_data
    result['timestamp'] = datetime.now().strftime("%d.%m %H:%M")
    json.dump(result, open('output.json', 'wb'), indent=4)


def update_servers_info(servers_names, user, password):
    """
        Пробежаться по всем серверам из СПИСКА ИМЕН и собрать инфу по ним
    """
    result = {'servers': {}}
    for server_name in servers_names:
        server_data = get_server_info(server_name, user, password)
        if server_data:
            result['servers'][server_name] = server_data
    result['timestamp'] = datetime.now().strftime("%d.%m %H:%M")
    json.dump(result, open('output.json', 'wb'), indent=4)


#@route('/', method='GET')
@get("/")
def wrapper():
    """
        Боттоловская обертка для скрипта
    """
    if request.GET.get('update', '').strip():
        servers_names = request.GET.getall('servers_names') # re.findall('[^,;. ]+', request.GET.get('servers_names', '').strip())
        update_servers_info(servers_names, 'emercom', 'emercom') if servers_names else update_servers_info_from_file()
        generated_data = json.load(open('output.json', "r"))
        open('last_output.json', 'wb').write(json.dumps(generated_data, indent=4))
        selected_data = request.GET.getall('servers_names')
    else:
        generated_data = json.load(open('last_output.json', "r"))
        selected_data = generated_data['servers'].keys()
    return template('ServerInfoTemplate.html', servers=generated_data['servers'], all_servers=settings_data['servers'].keys(),
                    selected=selected_data, timestamp=generated_data['timestamp'])

########## Настройка статических файлов для ботла ##############
@bottle_get('/<filename:re:.*\.js>')
def javascripts(filename):
    return static_file(filename, root='static/js')

@bottle_get('/<filename:re:.*\.css>')
def stylesheets(filename):
    return static_file(filename, root='static/css')

@bottle_get('/<filename:re:.*\.(jpg|png|gif|ico)>')
def images(filename):
    return static_file(filename, root='static/img')

debug(True)
#bottle_run(host='localhost', port=8080, reloader=True, server="twisted")
bottle_run(host='0.0.0.0', port=8080, reloader=False, server="twisted")


