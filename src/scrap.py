#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function
import os
import csv
from multiprocessing import Pool
from bs4 import BeautifulSoup
import zipfile
import click
import logging
import requests
import re
import json
import glob
from io import StringIO
from collections import OrderedDict

from natsort import natsorted, ns
from pathlib import Path
import xlwt

aep = 'SCRAP'
D = Path('/data')
log = logging.getLogger('assnat.scrapper')
LAW_URL = "http://data.assemblee-nationale.fr/static/openData/repository/{lawrepo}/dossiers_legislatifs_opendata/{lawid}/libre_office.csv"  # noqa
varnames = {
    'aid': "Numéro de l'amendement",
    'partie': "Partie de l'amendement",
    'auteur': "Auteur",
    'xml': 'URL Amendement format XML',
    'url': 'URL Amendement',
}
DEPUTES_URL = 'http://data.assemblee-nationale.fr/static/openData/repository/15/amo/deputes_senateurs_ministres_legislature/AMO20_dep_sen_min_tous_mandats_et_organes_XV.json.zip'  # noqa
DOSSIERS_LEGISLATTIFS = 'http://data.assemblee-nationale.fr/static/openData/repository/15/loi/dossiers_legislatifs/Dossiers_Legislatifs_XV.json.zip'  # noqa
DEPUTESD = D / 'deputes'


def fetch(url, p, decode=True, unzip=None):
    if unzip is None:
        if str(p).endswith('.zip'):
            unzip = True
            decode = False
    fetch = True
    if not os.path.exists(p.parent):
        p.parent.mkdir(parents=True)
    if os.path.exists(p) and not os.environ.get('FORCE_REDOWNLOAD'):
        fetch = False
    if fetch:
        log.info(f'Downloading {url} to {p}')
        req = requests.get(url)
        content = req.content
        mode = 'wb'
        if decode:
            content = content.decode('utf-8')
            mode = 'w'
        with open(p, mode) as fic:
            fic.write(content)
        if unzip:
            with zipfile.ZipFile(p, 'r') as zip_ref:
                zip_ref.extractall(p.parent)
    else:
        log.info(f'{url} already fetched to {p} (set FORCE_REDOWNLOAD=1)')


def download_general_csv(lawid, lawrepo):
    """."""
    csvp = D/f'{lawid}/law.csv'
    lurl = LAW_URL.format(**locals())
    fetch(lurl, csvp)
    with open(csvp) as f:
        data = f.read()
    reader = csv.DictReader(StringIO(data), dialect='excel')
    rows = [row for row in reader]
    return rows, data


def download_amendement(am, DEPUTES, ORGANES):
    """."""
    for v in varnames:
        am[v] = am.pop(varnames[v])
    am['json'] = am['xml'].replace('xml', 'json')
    am['uid'] = os.path.basename(am['xml']).split('.')[0]
    p = D/f'{am["lawid"]}/{am["uid"]}'
    for i in 'xml', 'json':
        xml = p / i
        fetch(am[i], xml)
    am['jsond'] = json.load(open(str(p/'json')))
    am['parpols'] = set()
    refs = set()
    asig = am['jsond']['signataires']['auteur']
    if asig['typeAuteur'] == 'Gouvernement':
        refs.add(asig['gouvernementRef'])
    else:
        refs.add(asig['acteurRef'])
    [refs.add(a)
     for a in am['jsond']['signataires']['cosignataires'].get('acteurRef', {})
     if DEPUTES.get(a)]
    am['signataires'] = []
    for a in refs:
        try:
            am['signataires'].append(DEPUTES[a])
        except KeyError:
            ORGANES['raw'][a]['libelle']

    [am['parpols'].add(d.get('parpol', 'NON-INSCRIT'))
     for d in am['signataires']]

    dtext = am['jsond']['pointeurFragmentTexte']['division']
    title = dtext['titre']
    if dtext['type'] == 'CHAPITRE':
        title = dtext['articleDesignation']
    am['art'] = title
    am['artpos'] = dtext['articleDesignation']
    am['sort'] = am['Sort de l\'amendement']
    am['text'] = am['jsond'].get('corps', {}).get(
        'contenuAuteur', {}).get('dispositif', '')
    am['expose'] = am['jsond'].get('corps', {}).get(
        'contenuAuteur', {}).get('exposeSommaire', '')
    am['date'] = am['jsond']['cycleDeVie']['dateDepot']
    return am


def general_tab(data, sheet="general", w=None):
    ws = w.add_sheet(sheet)
    general_rows = []
    columns = OrderedDict([
        ('aid', 'aid'),
        ('date', 'date'),
        ('Instance', 'Instance'),
        ('Cosignataire(s)', 'Cosignataire(s)'),
        ('parpols', 'partis politiques'),
        ('auteur', 'auteur'),
        ('art', 'article'),
        ('artpos', 'article position'),
        ('url', 'url'),
        ('sort', 'sort'),
        ('expose', 'Exposé'),
        ('text', 'Texte'),
    ])
    for i in data:
        am = data[i]
        row = OrderedDict()
        for i in columns:
            row[i] = am[i]
        general_rows.append(row)
    general_rows = natsorted(
        general_rows,
        key=lambda x: (
            f"{x['art']}{x['Instance']}{x['date']}{x['sort']}"
            f"{x['parpols']}{x['auteur']}{x['Cosignataire(s)']}"
            f"{x['aid']}").lower(),
        alg=ns.IGNORECASE)
    # headers
    for j, col in enumerate(columns):
        ws.write(0, j, columns[col])
    # row
    for i, row in enumerate(general_rows, 1):
        for j, col in enumerate(columns):
            val = row[col]
            if isinstance(val, (set, list)):
                val = ';'.join(val)
            if col in ['url']:
                val = xlwt.Formula(f'Hyperlink("{val}")')
            if col in ['text', 'expose']:
                val = BeautifulSoup(val).get_text()
            if col in ['Instance']:
                val = re.sub('Commission.*', 'Commission', val)
            ws.write(i, j, val)
    return w


def make_csvs(lawid, amendements, out=None, w=None):
    if out is None:
        out = D/f'export_{lawid}.xls'
    if w is None:
        w = xlwt.Workbook()
    general_tab(amendements, w=w)
    w.save(out)


def load_organe(organe, ORGANES=None):
    if ORGANES is None:
        ORGANES = OrderedDict()
    bn = os.path.basename(organe.split('.json')[0])
    with open(DEPUTESD/Path(f'json/organe/{bn}.json')) as fic:
        jdata = json.loads(fic.read())
    o = {}
    for i, v in {
        'uid': 'uid',
        'libelle': 'libelle',
        'libelleAbrev': 'libelleAbrev',
        'organeParent': 'parent',
        'codeType': 'codeType',
    }.items():
        o[v] = jdata['organe'][i]
    ORGANES['raw'][o['uid']] = o
    tp = ORGANES['type'].setdefault(o['codeType'], OrderedDict())
    tp[o['uid']] = o
    tp = ORGANES['type_label'].setdefault(o['codeType'], OrderedDict())
    tp[o['libelleAbrev']] = o
    return o


def load_depute(depute, DEPUTES=None, ORGANES=None):
    if DEPUTES is None:
        DEPUTES = OrderedDict()
    if ORGANES is None:
        ORGANES = OrderedDict()
    bn = os.path.basename(depute.split('.json')[0])
    with open(DEPUTESD/Path(f'json/acteur/{bn}.json')) as fic:
        jdata = json.loads(fic.read())
    o = {'uid': jdata['acteur']['uid']['#text']}
    DEPUTES[o['uid']] = o
    o.update(jdata['acteur']['etatCivil']['ident'])
    try:
        mandats = jdata['acteur']['mandats']['mandat']
        if isinstance(mandats, dict):
            mandats = [mandats]
        parpol = [a['organes']['organeRef']
                  for a in mandats if a['typeOrgane'] == 'PARPOL']
        parpolref = parpol[0]
        o['parpol'] = ORGANES['type']['PARPOL'][parpolref]['libelleAbrev']
    except IndexError:
        log.info(f'No parpol for {o["nom"]} {o["prenom"]}')


def load_deputes():
    DEPUTES = OrderedDict()
    ORGANES = OrderedDict()
    ORGANES['raw'] = OrderedDict()
    ORGANES['type'] = OrderedDict()
    ORGANES['type_label'] = OrderedDict()
    deputesp = DEPUTESD / 'deputessm.zip'
    fetch(DEPUTES_URL, deputesp)
    for js in glob.iglob(str(DEPUTESD/'json/organe/*.json')):
        load_organe(js, ORGANES)
    for js in glob.iglob(str(DEPUTESD/'json/acteur/*.json')):
        load_depute(js, DEPUTES, ORGANES)
    return DEPUTES, ORGANES


def download(lawid, amendement, DEPUTES, ORGANES):
    amendement["lawid"] = lawid
    return download_amendement(amendement, DEPUTES, ORGANES)


@click.command()
@click.option('--lawrepo', default="15")
@click.option('--lawid', help='law id',
              default=lambda: os.environ.get('LAWID', '41074'))
@click.option('--loglevel', default="INFO")
def parse(lawrepo, lawid, loglevel):
    """Get a law, its amendements and output a nice csv"""
    logging.basicConfig(level=getattr(logging, loglevel.upper()))
    DEPUTES, ORGANES = load_deputes()
    log.info('start')
    amendements = OrderedDict()
    csvdata, data = download_general_csv(lawid, lawrepo)
    pool = Pool()
    for a in pool.starmap(
        download,
        [(lawid, a, DEPUTES, ORGANES) for a in csvdata],
        chunksize=250
    ):
        amendements[a['uid']] = a
    make_csvs(lawid, amendements)


if __name__ == '__main__':
    parse()
# vim:set et sts=4 ts=4 tw=120:
