from flask import render_template, request, Response, jsonify
from flask_podcast import app
import pandas as pd
import psycopg2
import preprocess_text as pp
import os
from gensim import corpora, models, similarities
import Pyro4
from json import dumps


APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_STATIC = os.path.join(APP_ROOT, 'static')
APP_DATA = os.path.join(APP_STATIC, 'data')

# set up database connection
user = 'lindsay'          
#user = 'ubuntu'
host = 'localhost'
dbname = 'podcast'
con = None
con = psycopg2.connect(database = dbname, user = user)
cursor = con.cursor()

# load simserver
server = Pyro4.Proxy(Pyro4.locateNS().lookup('gensim.testserver'))

def pg_int_array(the_list):
  return '(' + ','.join(the_list) + ')'

def pd_to_json_dict(pd):
  pd = [dict([(colname, row[i]) for i, colname in enumerate(pd.columns)]) for row in pd.values]
  return pd

def decimal_default(obj):
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    raise TypeError

def special_replace(text):
    text = text.replace('\n', ' ')
    text = text.replace('\r', ' ')
    text = text.replace('\t', ' ')
    text = text.replace('\f', ' ')
    return text

@app.route('/')
def home():
  return render_template("home_base.html")

@app.route('/about')
def about():
  return render_template("about.html")

@app.route('/slides')
def slides():
  return render_template("slides.html")

@app.route('/check_input')
def podcast_check_input():
  name_query = request.args.get('podcast_name')
  name_query = '%' + name_query.lower() + '%'
  
  query = "SELECT clean_name, id FROM podcast WHERE lower(clean_name) LIKE %s;"
  data = (name_query, )
  cursor.execute(query, data)
  query_results = cursor.fetchall()

  query_results = pd.DataFrame(query_results, columns = ['clean_name', 'id'])

  print query_results

  name_results = []
  for i in range(query_results.shape[0]):
    name_results.append(dict(id=query_results.iloc[i]['id'], name=query_results.iloc[i]['clean_name'].decode('utf-8')))
  return render_template("check_input.html", name_results=name_results)

@app.route('/output')
def podcast_output():
  num_results = 100

  podcast_id = request.args.get('id')

  sim_tuple = server.find_similar(podcast_id)

  sim_df = pd.DataFrame(sim_tuple, columns=['id', 'similarity', 'null'])

  del(sim_df['null'])

  # add variables to identify searched and top
  sim_df['searched'] = [False] * sim_df.shape[0]
  sim_df['searched'][sim_df['id'] == podcast_id] = True
  sim_df['top'] = [False] * sim_df.shape[0]
  sim_df.loc[:num_results, 'top'] = True


  # take top ids
  ids = list(sim_df['id'].values)
  ids = [str(int(x)) for x in ids]
  ids = ids[:num_results]
  
  # query the db
  query = """
  SELECT name, view_url, artwork_url100, id, raw_summary
  FROM podcast
  WHERE id IN %s;
  """
  query = query.replace('\n', ' ')

  cursor.execute(query % (pg_int_array(ids)))
  query_results = cursor.fetchall()

  # convert to dataframe
  columnNames = ['name', 'view_url', 'artwork_url100', 'id', 'summary']
  podcast_results = pd.DataFrame(columns=columnNames)
  podcast_results['name'] = [x[0] for x in query_results]
  podcast_results['view_url'] = [x[1] for x in query_results]
  podcast_results['artwork_url100'] = [x[2] for x in query_results]
  podcast_results['id'] = [x[3] for x in query_results]
  podcast_results['summary'] = [x[4] for x in query_results]
  podcast_results['summary'] = [special_replace(x) for x in podcast_results['summary']]

  # merge with pca data
  sim_df['id'] = [int(x) for x in sim_df['id']]
  table_results = pd.merge(sim_df, podcast_results, how = 'inner', left_on='id', right_on='id')
  scatter_results = table_results.copy(deep=True)

  # convert to jsonlike
  podcast_results = []
  for i in range(num_results):
    podcast_results.append(dict(similarity=table_results.iloc[i]['similarity'], name=table_results.iloc[i]['name'].decode('utf-8').encode('ascii', 'ignore'), view_url=table_results.iloc[i]['view_url'], artwork_url100=table_results.iloc[i]['artwork_url100'], id=table_results.iloc[i]['id']))

  podcast_results_no_self = podcast_results[1:]

  #print podcast_results_no_self

  scatter_results['name'] = [str(x).replace('"', "'") for x in scatter_results['name']]
  scatter_results['summary'] = [str(x).replace('"', "'") for x in scatter_results['summary']]
  scatter_results['summary'] = [x.decode('utf-8').encode('ascii', 'ignore') for x in scatter_results['summary']]
  
  #merge_dict = pd_to_json_dict(scatter_results)
  merge_dict = scatter_results.to_json(orient="records")
  
  # get name of searched podcast
  query = "SELECT name FROM podcast WHERE id='%s'"
  cursor.execute(query % podcast_id)
  podcast_name = cursor.fetchall()
  podcast_name = podcast_name[0][0].decode('utf-8')


  # return render_template("output.html", podcast_results_no_self=podcast_results_no_self, podcast_results=merge_dict, search_name=podcast_name)
  return render_template("output_force_layout.html", podcast_results_no_self=podcast_results_no_self, podcast_results=merge_dict, search_name=podcast_name)

@app.route('/db_test')
def db_test():
   #sim_tuple = server.find_similar('17233')
  query = "SELECT name FROM podcast LIMIT 10;"
  cursor.execute(query) 
  return "pizza"

@app.route('/keyword_output', methods=['GET'])
def keyword_output():
  num_results=100

  search = request.args.get('keyword')
  doc = {'tokens' : pp.preprocess_text(search)} 
  
  sim_tuple = server.find_similar(doc)

  sim_df = pd.DataFrame(sim_tuple, columns=['id', 'similarity', 'null'])

  del(sim_df['null'])

  # take top ids
  ids = list(sim_df['id'].values)
  ids = [str(int(x)) for x in ids]
  ids = ids[:num_results]
  
  # query the db
  query = """
  SELECT name, view_url, artwork_url100, id, raw_summary
  FROM podcast
  WHERE id IN %s;
  """
  query = query.replace('\n', ' ')

  cursor.execute(query % (pg_int_array(ids)))
  query_results = cursor.fetchall()

  # convert to dataframe
  columnNames = ['name', 'view_url', 'artwork_url100', 'id', 'summary']
  podcast_results = pd.DataFrame(columns=columnNames)
  podcast_results['name'] = [x[0] for x in query_results]
  podcast_results['view_url'] = [x[1] for x in query_results]
  podcast_results['artwork_url100'] = [x[2] for x in query_results]
  podcast_results['id'] = [x[3] for x in query_results]
  podcast_results['summary'] = [x[4] for x in query_results]

  # merge with pca data
  sim_df['id'] = [int(x) for x in sim_df['id']]
  table_results = pd.merge(sim_df, podcast_results, how = 'inner', left_on='id', right_on='id')
  scatter_results = table_results.copy(deep=True)

  # convert to jsonlike
  podcast_results = []
  for i in range(num_results):
    podcast_results.append(dict(similarity=table_results.iloc[i]['similarity'], name=table_results.iloc[i]['name'].decode('utf-8').encode('ascii', 'ignore'), view_url=table_results.iloc[i]['view_url'], artwork_url100=table_results.iloc[i]['artwork_url100'], id=table_results.iloc[i]['id']))

  podcast_results_no_self = podcast_results[1:]

  
  scatter_results['name'] = [str(x).replace('"', "'") for x in scatter_results['name']]
  scatter_results['summary'] = [str(x).replace('"', "'") for x in scatter_results['summary']]
  scatter_results['summary'] = [x.decode('utf-8').encode('ascii', 'ignore') for x in scatter_results['summary']]
  
  merge_dict = scatter_results.to_json(orient="records")
  #merge_dict = pd_to_json_dict(scatter_results)
  #print merge_dict

  #return Response(dumps(merge_dict), mimetype="text/json")
  return render_template("output_force_layout.html", podcast_results_no_self=podcast_results, podcast_results=merge_dict, search_name=search)
