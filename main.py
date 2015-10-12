#!/usr/bin/env python
# -*- coding: utf-8 -*-

# import untangle
from pyquery import PyQuery as pq
import urllib
import urllib2
import requests
import json
import redis
from termcolor import colored
import urlparse
import wget

import sys    # sys.setdefaultencoding is cancelled by site.py
reload(sys)    # to re-enable sys.setdefaultencoding()
sys.setdefaultencoding('utf-8')

debug=True

db = redis.StrictRedis(host='localhost', port=6379, db=0)

def print_success(msg):
    print(colored(msg, 'green', attrs=['bold']))

def print_warning(msg):
    print(colored(msg, 'red', attrs=[]))

def print_error(msg):
    print(colored(msg, 'red', attrs=['bold']))

def print_debug(msg):
    print(colored(msg, 'yellow', attrs=[]))


def get_pagedata(doc):
    return json.loads(doc('#pagedata').attr('data-blob'))

def get_item_id(doc):
    pagedata = get_pagedata(doc)
    for e in pagedata["login_action_url"].split("&"):
        if "item_id" in e:
            item_id = e.split("=")[1]

    # print("item_id found: ", item_id)
    return item_id

def get_album_name_from_url(url):
    parts = url.split('/')
    if len(parts) < 5:
        print_error('Invalid url (not tested)')
        return None
    return parts[4]

def album_info_from_url(url):
    #http://lasedades.bandcamp.com/album/Todo
    parts = url.split('/')
    if len(parts) < 5:
        print_error('Invalid url (not tested)')
        return None

    album = parts[4]
    band = parts[2].split('.')[0]
    return (band, album)

def get_name_key_from_album_info(url):
    info = album_info_from_url(url)
    return info[0].lower() + "-" + info[1].lower()

def set_as_checked(key):
    print_debug('{0} setted as checked!'.format(key))
    return db.sadd('checked_albums', key)

def was_requested(album_id):
    r = db.hmget('album:' + str(album_id), "requested")[0]
    return int(r) != 0


def set_as_requested(album_id):
    db.hmset('album:' + str(album_id), {'requested': 1})

def set_as_downloaded(album_id):
    db.hmset('album:' + str(album_id), {'downloaded': 1})


def get_albums(tag=None):
    print_debug('Getting albums...')
    d = pq(url='http://bandcamp.com/tag/{0}'.format(tag if tag else 'argentina'))
    results = d('div.results .item')
    # print(results.html())

    ret = {}
    i = 0
    for album in results.items('a'):
        ret[album.attr['title']] = album.attr['href']
        # print(album.attr['title'] + " => " + album.attr['href'])

    print "Found {0} albums".format(len(ret))
    return ret

def is_free(doc):
    print_debug('Checking album...')
    h4 = doc('.download-link.buy-link').parents('h4')
    if len(h4) == 0:
        print("No hay h4")
        return False
    # if len(h4) != 1: print("Hay mas de un h4")
    return len(h4[0]) == 2

def check_album(url):
    print_debug('Checking {0}'.format(url))
    return is_free(pq(url=url))

def request_album(doc, address=None):

    # is string? no problemo, assume it's an url
    if isinstance(doc, basestring):
        doc = pq(url=doc)

    address = address or 'grabberyyz@yopmail.com'

    album_id = int(get_item_id(doc))

    if was_requested(album_id):
        print_warning("Album", album_id, " already requested")
        return False

    payload = {
        'encoding_name': 'none',
        'item_id': album_id,
        'item_type': 'album',
        'address': address,
        'country': 'Argentina',
        'postcode': '1431'
    }

    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36',
        'Referer': 'http://fertildiscos.bandcamp.com/album/we-are',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    cookies = dict(
        client_id='D196C900F27FFD10653B12036CB05872D0ACD3358ECAA0A4250787BB1982AF4B',
        BACKENDID='bender04-5',
    )

    # print(payload)
    print_debug("Requesting album {0}".format(album_id))
    if debug:
        return False
    else:
        response = requests.post(
            "http://fertildiscos.bandcamp.com/email_download",
            data=payload,
            headers=headers,
            cookies=cookies
        )

    if response.status_code != 200: print "ERROR"
    return response.status_code == 200

def filter_free_albums(albums=None):
    albums = albums or get_albums()

    # return {k:v for k,v in albums.iteritems() if check_album(v)}
    ret = {}
    for k,v in albums.iteritems():
        # if its already on the db, we skip it.
        album_key = get_name_key_from_album_info(v)
        print "Checking if", k, "is free or not"
        if db.sismember('checked_albums', album_key):
            print album_key + " already checked, we skip it"
            continue

        album = pq(url=v)
        free = is_free(album)
        if free:
            ret[get_item_id(album)] = v

        set_as_checked(album_key)
        if free:
            print_success("Album {0} is free!".format(k))
        else:
            print "Album {0} NOT is free!".format(k)

    return ret

def get_free_albums(tag=None):
    return filter_free_albums(tag)

# print filter_free_albums()
# print get_pagedata(d)
# print get_item_id(d)
# print is_free(d)
# print(request_album(d).text)
# print(get_albums("argentina"))
# print("Parsed")

##

def process_email(uri):
    print "Processing email..."
    url = "http://www.yopmail.com/en/" + uri
    d = pq(url=url)
    link = d.find('#mailmillieu a').attr('href')
    return link

def get_inbox(login='grabberyyz', max_pages=100):
    print "Getting inbox..."
    last_email = db.get('last_email')

    ret = []
    page = 1
    run = True
    while(page <= max_pages and run):
        print_debug("page: " + str(page))
        url = 'http://www.yopmail.com/en/inbox.php?login={0}&p={1}&v=2.6'.format(login, page)
        d = pq(url=url)
        emails = d.find('a.lm')

        if page == 1:
            td = d.find('td.alm')
            if not td:
                # no more than 1 page
                max_pages = 1
            else:
                title = td.find('a.igif.next').attr('title')
                max_pages = int(title.split('/')[1])
                print_debug("New max_pages=" + str(max_pages))

        for e in emails.items():
            href = e.attr('href')
            if href == last_email:
                run=False
                break
            ret.append(href)
            print_debug(href)

        page+=1

    # print(emails)
    print "Found {0} new emails".format(len(ret))
    return ret

# print(get_inbox())
# print(process_email('mail.php?b=grabberyyz&id=me_ZGHkZQRkZGtlZQN5ZQNjZwxkBQx1AN=='))

def store_free_albums(albums=None):
    free_albums = albums or filter_free_albums()

    for album_id,value in free_albums.iteritems():
        print "Store album", album_id
        entry = {
            'id': album_id,
            'url': value,
            'requested': 0,
            'downloaded': 0,
            'download_url': ''
        }
        db.sadd('albums', str(album_id))
        db.hmset('album:' + str(album_id), entry)


def download_free_albums(encode='flac'):
    pass

def get_album_id_from_download_url(url):
    parsed = urlparse.urlparse(url)
    return urlparse.parse_qs(parsed.query)['id'][0]

def set_download_url(download_url):
    album_id = get_album_id_from_download_url(download_url)
    print "Setting url to album", album_id
    db.hmset('album:' + str(album_id), {'download_url': download_url})

def transform_download_url(url):
 #from http://bandcamp.com/download?from=email&id=3415460527&payment_id=2501284666&sig=3df7cac0c2f51a081da7f16554ff2353&type=album
 # to  http://popplers5.bandcamp.com/download/album?enc=flac&id=3415460527&payment_id=2501284666&sig=3df7cac0c2f51a081da7f16554ff2353
 #     http://popplers5.bandcamp.com/download/album?enc=flac&id=3415460527&payment_id=3185211738&sig=a94a5ac388f0aa252c699deea0a0aba9
#      http://popplers5.bandcamp.com/download/album?enc=flac&id=3415460527&payment_id=3185211738&sig=a94a5ac388f0aa252c699deea0a0aba9
    parsed = urlparse.urlparse(url)
    params = urlparse.parse_qs(parsed.query)

    server = 'popplers5'
    encode = 'flac'
    album_id = params['id'][0]
    payment_id = params['payment_id'][0]
    signature = params['sig'][0]

    print_debug("from: " + url)
    url = "https://{0}.bandcamp.com/statdownload/album?enc={1}&id={2}&payment_id={3}&sig={4}".format(
        server, encode, album_id, payment_id, signature
    )
    print_debug("to: " + url)
    return url

def download_album(url):
# https://popplers5.bandcamp.com/statdownload/album?enc=flac&id=2832935911&payment_id=2851505253&sig=e4b8318cb3ef4cbaf038fd15e35d4a60&.rand=1159744093003&.vrs=1
#http://p1.bcbits.com/download/album/18a04640ba8f2edfe865adc0df6bcd2f0/flac/3718862184?id=3718862184&payment_id=1592516836&sig=f28deca45f6ae91e22ccdd2717cf575b&e=1445217303&h=f5f68167bf38f2cb12f1c5f9f062ccd8

    album_id = get_album_id_from_download_url(url)

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': url,
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36',
    }

    cookies = dict(
        BACKENDID='bender04-5',
        client_id='D196C900F27FFD10653B12036CB05872D0ACD3358ECAA0A4250787BB1982AF4B',
    )


    parsed = urlparse.urlparse(url)
    params = urlparse.parse_qs(parsed.query)
    payload = {
        'enc': 'flac',
        'id': params['id'][0],
        'payment_id': params['payment_id'][0],
        'sig': params['sig'][0],
        '.rand':244072908628,
        '.vrs':1
    }

    url = transform_download_url(url)
    response = requests.get(
        "https://popplers5.bandcamp.com/statdownload/album?",
        data=payload,
        headers=headers,
        cookies=cookies
    )
    if response.status_code != 200:
        print_error("an error has occurred trying to get the file download url.")
        return False
    else:
        response = json.loads(response.text)
        file_download_url = response['download_url']

    # download = urllib.URLopener()
    # download.retrieve(file_download_url,  str(album_id) + ".zip")
    wget.download(file_download_url)
    db.sadd("downloaded", str(album_id))

def work(tag=None):
    albums = get_free_albums(tag)
    store_free_albums(albums)

    for album_id, album_url in albums.iteritems():
        requested = request_album(album_url)
        if requested:
            set_as_requested(album_id)
        if requested:
            print_success("Album {0} was requested!".format(get_album_name_from_url(album_url)))
        else:
            print_error("Album {0} was NOT requested!".format(get_album_name_from_url(album_url)))

    mails = get_inbox()


# http://bandcamp.com/download?from=email&id=3415460527&payment_id=2501284666&sig=3df7cac0c2f51a081da7f16554ff2353&type=album
    for m in mails:
        if m == db.get('last_email'):
            print("no more new emails!")
            break
        set_download_url(process_email(m))

    db.set('last_email', mails[0])

    for elem in db.sdiff('albums', 'downloaded'):
        album = db.hgetall('album:' + str(elem))
        # need an album model.
        if len(album['download_url']) > 5:
            print_success('Downloading {0}'.format(album['download_url']))
            download_album(album['download_url'])
            set_as_downloaded(album['id'])
            print_success('Download complete!')


# get_inbox()
work()
