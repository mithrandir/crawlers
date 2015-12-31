#! /usr/bin/python2.7
# -*- coding: utf-8 -*-

from __future__ import unicode_literals
import os
import re

import gevent
from gevent import monkey; monkey.patch_all()
import lxml
import pandas as pd

from settings import LIKMS, DIR, X
import utils


def extract_row_contents(row):

    def extract_subcolumn(elem):

        def urls_in_image(image):
            has_url = image.xpath('@onclick')
            url = None
            if has_url:
                matched = re.search(r'(.*)\((.*)\)', has_url[0])
                if matched.group(1)=='javascript:openConfInfo':
                    parts = re.sub('[ \']', '', matched.group(2)).split(',')
                    url = '%s/ConfInfoPopup.jsp?bill_id=%s&proc_id=%s' % (LIKMS, parts[0], parts[1])
                elif matched.group(1)=='javascript:OpenConfFile':
                    parts = re.sub(r'.*\((.*)\)', r'\g<1>',\
                            has_url[0])\
                            .replace(' ', '').replace('\'','')\
                            .split(',')
                    if len(parts) == 2:
                        '''New rule (2013-11-28)
                        See: http://likms.assembly.go.kr/bill/WebContents/js/common.js
                        '''
                        url = 'http://likms.assembly.go.kr/record/new/getFileDown.jsp?CONFER_NUM=%s' % parts[1]
                    elif parts[1].isdigit() and int(parts[1]) > 208:
                        url = '%sdata2/%s/pdf/%s' % (parts[0], parts[1], parts[2])
                    else:
                        url = '%sdata1/%s/%s' % (parts[0], parts[1], parts[2])
                elif matched.group(1)=='javascript:ShowProposer':
                    parts = re.sub('[ \']', '', matched.group(2))
                    url = '%s/CoactorListPopup.jsp?bill_id=%s' % (LIKMS, parts)
            return url

        texts = filter(None, (t.strip()\
                    for t in elem.xpath('descendant::text()')))

        if elem.xpath('table'):
            a_links   = [link.xpath('td/a/@href') for link in elem.xpath('descendant::tr')]
        else:
            i, node = 0, []
            elem_node = elem.xpath('descendant::node()')
            for j, n in enumerate(elem_node):
                if type(n)==lxml.etree._Element:
                    if n.tag=='br':
                        node.append(elem_node[i:j])
                        i = j
            a_links = list()
            for n in node:
                tmp = []
                for m in n:
                    if type(m)==lxml.etree._ElementUnicodeResult:
                        desc = m.strip()
                        a_links.append(tmp)
                        tmp = []

                    elif type(m)==lxml.etree._Element and m.tag not in ['img', 'br']:
                        tmp.append(m.xpath('@href')[0])
                    else:
                        pass

        img_links = [urls_in_image(img) for img in elem.xpath('descendant::img')]
        links     = a_links or img_links

        urls      = map(None, texts, links) if links else texts[0] if texts else None

        return urls

    def extract_subrows(elem_subrows):
        subrows = []
        for elem_subrow in elem_subrows:
            subrows.append(extract_subcolumn(elem_subcolumn)\
                    for elem_subcolumn in elem_subrow)
        return subrows


    titles = row.xpath('descendant::span[@class="text8" or @class="text11"]/text()')
    tables = row.xpath('descendant::table[@bgcolor="#D1D1D1"]')
    table_infos = []
    for table in tables:
        rows = table.xpath('tbody/tr')
        headers = rows[0].xpath('descendant::div/text()')
        elem_subrows = [row.xpath('descendant::td/div')  for row in rows[1:]]
        subrows = extract_subrows(elem_subrows)
        table_infos.append([dict(zip(headers, subrow)) for subrow in subrows])

    return dict(zip(titles, table_infos))


def extract_specifics(assembly_id, bill_id, meta):

    def extract_file_links(c):
        url = c.xpath('descendant::a/@href')
        i, node = 0, []
        elem_node = c.xpath('descendant::node()')
        for j, n in enumerate(elem_node):
            if type(n)==lxml.etree._Element:
                if n.tag=='br':
                    node.append(elem_node[i:j])
                    i = j
        links = dict()
        for n in node:
            tmp = []
            for m in n:
                if type(m)==lxml.etree._ElementUnicodeResult:
                    desc = m.strip()
                    links[desc] = tmp
                    tmp = []

                elif type(m)==lxml.etree._Element and m.tag not in ['img', 'br']:
                    tmp.append(m.xpath('@href')[0])
                else:
                    pass
        return links

    def extract_meeting_num(c):
        s = c.xpath('descendant::text()')[0]
        m = re.search(ur'제(.*)대.*제(.*)회', s)
        return [int(e) for e in m.groups()]

    def status_info(es, et, status_en):
        subjects = es.xpath('text()')[0]
        headers = [t[1] for t in utils.get_elem_texts(et, 'td')]

        elem_contents = [c for c in es.xpath(X['timeline']['%s_contents' % status_en]) if type(c)==lxml.etree._Element]
        elem_rows = [ec.xpath('td') for ec in elem_contents]

        rows = []
        for row in elem_rows:
            columns = []
            for column in row:
                links = column.xpath('descendant::a')
                images = column.xpath('descendant::img')
                if links:
                    columns.append([link.xpath('@href')[0] for link in links])
                elif images:
                    parts = re.sub(r'.*\((.*)\)', r'\g<1>',\
                            images[0].xpath('@onclick')[0])\
                            .replace(' ', '').replace('\'','')\
                            .split(',')
                    if parts[1] > 208:
                        url = '%sdata2/%s/pdf/%s' % (parts[0], parts[1], parts[2])
                    else:
                        url = '%sdata1/%s/%s' % (parts[0], parts[1], parts[2])
                    columns.append(url)
                else:
                    columns.append(column.xpath('descendant::text()')[1].strip())
            rows.append(dict(zip(headers, columns)))
        return rows

    def extract_extra_info(meta, c):
        extra_infos = dict()
        current_category = None
        for node in r:
            if node.tag == 'span' and node.get('class') == 'text11':
                current_category = node.text.strip()
                current_category = '대안반영폐기 의안목록' if current_category.startswith('대안반영폐기 의안목록') else current_category
                continue

            if current_category == None:
                continue

            extra_infos[current_category] = extra_infos[current_category] if extra_infos.has_key(current_category) else []
            content = None
            if current_category == '비고':
                content = extract_remark(node)
            elif current_category == '대안':
                content = extract_bill_id_from_link(meta, node)
            elif current_category == '대안반영폐기 의안목록':
                content = extract_bill_id_from_link(meta, node)
            else:
                content = lxml.html.tostring(node)

            if content:
                extra_infos[current_category].append(content)
        return extra_infos

    def extract_remark(c):
        try:
            if c.tag == 'br':
                return c.tail.strip()
            else:
                return c.text.strip()
        except AttributeError:
            return None

    def extract_bill_id_from_link(meta, c):
        # Assume this is <a> tag
        href = c.get('href')
        match = re.match('/bill/jsp/BillDetail.jsp\?bill_id=(.*)', href)
        if match:
            return meta.query('link_id == @match.group(1)')['bill_id'].values[0]
        return None

    fn          = '%s/%d/%s.html' % (DIR['specifics'], assembly_id, bill_id)
    page        = utils.read_webpage(fn)
    table       = utils.get_elems(page, X['spec_table'])[1]
    timeline    = page.xpath(X['spec_timeline'])[0]

    title         = page.xpath(X['spec_title'])[0].strip().replace('"','')
    status_detail = ' '.join(page.xpath(X['spec_status'])).strip()
    statuses      = filter(None,\
                    (s.strip() for s in\
                    ' '.join(\
                    s for s in timeline.xpath(X['spec_timeline_statuses'])\
                    if not type(s)==lxml.etree._Element)\
                    .split('\n')))
    status_infos  = [filter(None, i.split('*'))\
                    for i in timeline.xpath(X['spec_timeline_status_infos'])]
    row_titles = [' '.join(e.xpath('td/text()')).strip()\
            for i, e in enumerate(table.xpath('tbody/tr')) if i%4==0]
    elem_row_contents = [e.xpath('td[@class="text6"]')[0]\
            for i, e in enumerate(table.xpath('tbody/tr')) if i%4==1]
    status_dict   = {}

    for i, r in enumerate(elem_row_contents):
        if row_titles[i]!='부가정보':
            status_dict[row_titles[i]] = extract_row_contents(r)
        else:
            status_dict[row_titles[i]] = extract_extra_info(meta, r)

    headers = ['assembly_id', 'bill_id', 'title', 'status_detail', 'statuses', 'status_infos', 'status_dict']
    specifics = [assembly_id, bill_id, title, status_detail, statuses, status_infos, status_dict]

    return dict(zip(headers, specifics))

def extract_summaries(assembly_id, bill_id):
    #TODO: 제안이유 & 주요내용 분리하기
    try:
        fn = '%s/%s/%s.html' % (DIR['summaries'], assembly_id, bill_id)
        page = utils.read_webpage(fn)
        summaries = [e.replace('？', '/').strip()\
                for e in utils.get_elems(page, X['summary'])]
        return summaries
    except IOError as e:
        return None

def extract_proposers(assembly_id, bill_id):
    #TODO: 찬성의원 목록에 의원 이름이 있는 경우가 있는자 확인
    fn = '%s/%s/%s.html' % (DIR['proposers'], assembly_id, bill_id)
    page = utils.read_webpage(fn)
    elems = utils.get_elems(page, X['proposers'])
    if assembly_id < 19:
        return elems
    else:
        key = ['name_kr', 'party', 'name_cn']
        values = [filter(None, re.split('[\(/\)]', e)) for e in elems]
        return [{k: v for k, v in zip(key, value)} for value in values]

def extract_withdrawers(assembly_id, bill_id):
    fn = '%s/%s/%s.html' % (DIR['withdrawers'], assembly_id, bill_id)
    page = utils.read_webpage(fn)
    return utils.get_elems(page, X['withdrawers'])

def include(meta, bill_id, attr):
    value = list(meta.ix[meta['bill_id']==str(bill_id), attr])[0]
    if pd.isnull(value):
        return None
    return value

def parse_page(assembly_id, bill_id, meta, directory):

    fn = '%s/%s.json' % (directory, bill_id)

    d = extract_specifics(assembly_id, bill_id, meta)
    d['proposers']      = extract_proposers(assembly_id, bill_id)
    d['summaries']      = extract_summaries(assembly_id, bill_id)
    d['withdrawers']    = extract_withdrawers(assembly_id, bill_id)
    d['proposed_date']  = include(meta, bill_id, 'proposed_date')
    d['decision_date']  = include(meta, bill_id, 'decision_date')
    d['link_id']        = include(meta, bill_id, 'link_id')
    d['proposer_type']  = include(meta, bill_id, 'proposer_type')
    d['status']         = "계류" if include(meta, bill_id, 'status')==1 else "처리"

    utils.write_json(d, fn)

def html2json(assembly_id, range=(None, None), bill_ids=None):
    if bill_ids is not None and not bill_ids:
        return

    metafile = '%s/%d.csv' % (DIR['meta'], assembly_id)
    print metafile
    meta = pd.read_csv(metafile, dtype={'bill_id': object, 'link_id': object})

    jsondir = '%s/%s' % (DIR['data'], assembly_id)
    utils.check_dir(jsondir)

    if not bill_ids:
        bill_ids = meta['bill_id'][range[0]:range[1]]
    jobs = [gevent.spawn(parse_page, assembly_id, bill_id, meta, jsondir) for bill_id in bill_ids]

    gevent.joinall(jobs)
