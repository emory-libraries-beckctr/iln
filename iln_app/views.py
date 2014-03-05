import os
import re
import collections
from urllib import urlencode
import logging

from django.conf import settings
from django.shortcuts import render, render_to_response
from django.http import HttpResponse, Http404
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.template import RequestContext

from iln_app.models import Volume_List, Volume, Article, Fields, Figure, InterpGroup
from iln_app.forms import ArticleSearchForm, IllustrationSearchForm

from eulxml.xmlmap.core import load_xmlobject_from_file
from eulxml.xmlmap.teimap import Tei, TeiDiv, _TeiBase, TEI_NAMESPACE, xmlmap
from eulcommon.djangoextras.http.decorators import content_negotiation
from eulexistdb.query import escape_string
from eulexistdb.exceptions import DoesNotExist, ReturnedMultiple

logger = logging.getLogger(__name__)

def index(request):
  return render_to_response('index.html', context_instance=RequestContext(request))
  
def introduction(request):
  return render_to_response('introduction.html', context_instance=RequestContext(request))

def bibliography(request):
  file = xmlmap.load_xmlobject_from_file(filename=os.path.join(settings.BASE_DIR, 'static', 'xml', 'bibl.xml'))
  body = file.xsl_transform(filename=os.path.join(settings.BASE_DIR, '..', 'iln_app', 'xslt', 'bibl.xsl'))
  return render_to_response('bibliography.html', {'body' : body.serializeDocument()}, context_instance=RequestContext(request))

def about(request):
  return render_to_response('about.html', context_instance=RequestContext(request))

def links(request):
  file = xmlmap.load_xmlobject_from_file(filename=os.path.join(settings.BASE_DIR, 'static', 'xml', 'links.xml'))
  body = file.xsl_transform(filename=os.path.join(settings.BASE_DIR, '..', 'iln_app', 'xslt', 'links.xsl'))
  return render_to_response('links.html', {'body' : body.serializeDocument()}, context_instance=RequestContext(request))

def searchform(request):
    "Search by keyword/author/title/article_date"
    form_txt= ArticleSearchForm(request.GET)
    form_img = IllustrationSearchForm(request.GET) # Not sure if this can be in the same view.  
    response_code = None
    txt_context = {'searchform': form_txt}
    img_context = {'searchform': form_img}
    search_opts = {}
    number_of_results = 20
      
    if form_txt.is_valid():
        if 'keyword' in form_txt.cleaned_data and form_txt.cleaned_data['keyword']:
            search_opts['fulltext_terms'] = '%s' % form_txt.cleaned_data['keyword']
        if 'title' in form_txt.cleaned_data and form_txt.cleaned_data['title']:
            search_opts['head__fulltext_terms'] = '%s' % form_txt.cleaned_data['title']
        if 'article_date' in form_txt.cleaned_data and form_txt.cleaned_data['article_date']:
            search_opts['date__contains'] = '%s' % form_txt.cleaned_data['article_date']
                
        articles = Article.objects.only("id", "head", "vol", "issue", "pages", "date", "bib", "volume_id").filter(**search_opts)

        searchform_paginator = Paginator(articles, number_of_results)
        
        try:
            page = int(request.GET.get('page', '1'))
        except ValueError:
            page = 1
        # If page request (9999) is out of range, deliver last page of results.
        try:
            searchform_page = searchform_paginator.page(page)
        except (EmptyPage, InvalidPage):
            searchform_page = searchform_paginator.page(paginator.num_pages)

        txt_context['articles'] = articles
        txt_context['articles_paginated'] = searchform_page
        txt_context['keyword'] = form_txt.cleaned_data['keyword']
        txt_context['title'] = form_txt.cleaned_data['title']
        txt_context['article_date'] = form_txt.cleaned_data['article_date']
           
        response = render_to_response('search_results.html', txt_context, context_instance=RequestContext(request))
                 
    else:
        response = render(request, 'search.html', {"searchform": form_txt})
       
    if response_code is not None:
        response.status_code = response_code
    return response

def article_display(request, div_id):
  "Display the contents of a single article."
  if 'keyword' in request.GET:
    search_terms = request.GET['keyword']
    url_params = '?' + urlencode({'keyword': search_terms})
    filter = {'highlight': search_terms}    
  else:
    url_params = ''
    filter = {}
  try:
    return_fields = ['article', 'prevdiv_id', 'prevdiv_title', 'prevdiv_vol', 'prevdiv_issue', 'prevdiv_pages', 'prevdiv_extent', 'prevdiv_type', 'nextdiv_id', 'nextdiv_title', 'nextdiv_vol', 'nextdiv_issue', 'nextdiv_pages', 'nextdiv_extent', 'nextdiv_type', 'volume_id', 'volume_title', 'head', 'title', 'vol', 'issue', 'pages', 'date', 'identifier_ark', 'contributor', 'publisher', 'rights', 'issued_date', 'series']
    div = Article.objects.only(*return_fields).filter(**filter).get(id=div_id)
    body = div.article.xsl_transform(filename=os.path.join(settings.BASE_DIR, '..', 'iln_app', 'xslt', 'article.xsl'))
    return render_to_response('article_display.html', {'div': div, 'body' : body.serialize()}, context_instance=RequestContext(request))
  except DoesNotExist:
        raise Http404

def volumes(request):
  volumes = Volume_List.objects.only('id', 'head', 'docDate', 'divs').order_by('id')
  div_count_dict = {}
  fig_count_dict = {}
  for volume in volumes:
    div_list = []
    fig_list = []
    div_count = len(volume.divs)
    div_count_dict[volume.id] = (div_count)
    for div in volume.divs:
      fig_count = len(div.figs)
      fig_count_dict[volume.id] = (fig_count)
  
  return render_to_response('volumes.html', {'volumes': volumes, 'div_count_dict': div_count_dict, 'fig_count_dict': fig_count_dict}, context_instance=RequestContext(request))

def volume_display(request, vol_id):
  "Display the contents of a single volume."
  volume = Volume.objects.get(id__exact=vol_id)
  return render_to_response('volume_display.html', {'volume': volume,}, context_instance=RequestContext(request))

def volume_xml(request, vol_id):
  "Display the xml of a single volume."
  try:
    doc = Volume.objects.get(id__exact=vol_id)
  except:
    raise Http404
  tei_xml = doc.serializeDocument(pretty=True)
  return HttpResponse(tei_xml, mimetype='application/xml')

def illustrations(request):
  #Using separate queries for volumes and figures
  figures = Figure.objects.all()
  volumes = Volume_List.objects.only('id', 'head', 'docDate', 'figs').order_by('id')
  for fig in figures:
    vol_id = fig.vol_id
    fig_name = str(fig.url).rstrip(".jpg")
    div_data = [fig.vol, fig.issue, fig.pages, fig.date]

'''
  #Query only for the volumes
  volumes = Volume_List.objects.only('id', 'head', 'docDate', 'divs', 'figs').order_by('id')
  div_count_dict = {}
  fig_count_dict = {}
  fig_url_dict = {}
  for volume in volumes:
    div_list = []
    fig_list = []
    for div in volume.divs:
      div_list.append("n")
    div_count = len(div_list)
    div_count_dict[volume.id] = (div_count)
    for fig in volume.figs:
      figname = str(fig.url).rstrip(".jpg")
      fighead = fig.head
      #These next four variable are not functional.  Trying to pull volume-level but this links to the wrong model.  
      figvol = fig.vol
      figissue = fig.issue
      figpage = fig.pages
      figdate = fig.date
      fig_list.append(figname)
      #Dictionary to store results; list of lists will only return last result in the query.
      fig_url_dict[figname] = (volume.id, fighead, figvol, figissue, figpage, figdate)
    fig_count = len(fig_list)
    fig_count_dict[volume.id] = (fig_count)
'''
  return render_to_response('illustrations.html', {'volumes':volumes, 'figures':figures, 'vol_id':vol_id, 'fig_name':fig_name, 'div_data':div_data}, context_instance=RequestContext(request))

def illus_subj(request):
  "View list of subjects for illustrations"
  groups = InterpGroup.objects.only('items', 'name')
  return render_to_response('subjects.html', {'groups' : groups}, context_instance=RequestContext(request))

  
