__author__ = "@g30v4"
__license__ = "GPL"
__version__ = "1.0.0"
__maintainer__ = "@g30v4"
__status__ = "Development"
__date__ = "19/December/2021"

'''
Script to extract tweets with the API and Scrapy methods 
& generate a community relationship cluster graph
'''

# imports
import os
import random
import pymongo
import requests
import pandas as pd
import networkx as nx
from time import sleep
from dateutil.parser import *
import matplotlib.pyplot as plt
from configparser import RawConfigParser

# Get config
config = RawConfigParser()
config.read(os.path.join(os.path.dirname(__file__), 'twitter.cfg'))

# Settings
cfg = {
    'twitter' : {
        'oauth': {
            'app_key' : config['credentials']['app_key'], #config.get('credentials','app_key'), #
            'app_secret': config.get('credentials','app_secret'),
            'access_token' : config.get('credentials','access_token'),
            'token_secret' : config.get('credentials','token_secret'),
            'bearer_token' : config.get('credentials','bearer_token'),
        },
        'scraper' : {
            'authorization': config.get('scraper','authorization'),
            'x-guest-token': config.get('scraper','x-guest-token'),
            'agent_default': config.get('user-agent','agent_default'),
        },
        'endpoints': {
            'search' : 'https://api.twitter.com/2/tweets/search/recent',
            'friendsIds' : 'https://api.twitter.com/1.1/friends/ids.json',
            'searchCrw' : 'https://twitter.com/i/api/2/search/adaptive.json'
        }
        
    },
    'mongo': {
        'uri': config.get('mongodb','uri')
    }
}

# Search Params Api V2
searchParams = {
    'expansions' : 'author_id,entities.mentions.username,referenced_tweets.id,referenced_tweets.id.author_id,in_reply_to_user_id',
    'tweet.fields' : 'in_reply_to_user_id,created_at',
    'user.fields' : 'location,public_metrics',
    'max_results' : 100 # max data recover
}

# Search Scrapy Params
searchScrapyParams = {
    'tweet_mode' : 'extended',
    'query_source' : 'typed_query'
}

# Mongo Client Coneection
client = pymongo.MongoClient(cfg['mongo']['uri'])
db  = client['case2_sna']

# Random Tokens , process more fast friend 
rnd_tokens = [config.get('credentials','bearer_token'), config.get('credentials','bearer_token1'), config.get('credentials','bearer_token2')]

# var globals
query = "#Quito"
limit_tweets = 1000
users = []
referenced_tweets = []
tweets = []
tweet_list_ids = []
num_req_friends = 0
# Graph Instance
G=nx.DiGraph()

# OTHERS UTILS METHODS
def parseDate(dateString):
    '''String to date'''
    if dateString:
        date = parse(dateString, ignoretz=True)
        return date
    return None

def convertDfAndExport(tweets, file):
    '''Convert python list to Pandas Dataframe '''
    df = pd.DataFrame(tweets)
    df.to_csv(file)
    return df

def loadDataFrame(file):
    '''Load Dataframe, recover process'''
    df = pd.read_csv(file)
    print(df.sample(20))
    return df

def insertDb(conx, data, isOne):
    '''Dinamic insert in MOngoDB'''
    if isOne: #onlyOne
        try:
            x = conx.insert_one(data) 
        except pymongo.errors.DuplicateKeyError:
            pass
    else:
        x = conx.insert_many(data, ordered = False)

def sleepProcess(condition, time):
    '''Method to sleep process, used because twitter endpoints has rate limits'''
    if condition:
        print("sleep process...")
        sleep(time)
        

def getAllUniqueUser(df):
    '''Merge all unique users extracted'''
    p_user = df['screen_name'].tolist() # principal user
    r_user = [rt for rt in df['retweet_user'].tolist() if rt != 'NA'] # retweet users
    m_user = [m for m in df['mention'].tolist() if m] # mentions users
    all = list(set(p_user + r_user + m_user))
    all_user = [u for u in all if type(u) == str]
    return all_user

# RECOVER TWEETS METHODS
## API METHODS
def searchTweets(query, params={}, max_results=10): #, 
    url = cfg['twitter']['endpoints']['search']
    payload = {
        'query': query,
        'max_results': max_results
    }
    # Add expansions
    if params.get('expansions'):
        payload['expansions']= params['expansions']
    # Add tweet.fields
    if params.get('tweet.fields'):
        payload['tweet.fields']= params['tweet.fields']
    # Add user.fields
    if params.get('user.fields'):
        payload['user.fields']= params['user.fields']
    # Max Result
    if params.get('max_results'):
        payload['max_results'] = params['max_results']
    # Next TOken pagination
    if params.get('next_token'):
        payload['next_token'] = params['next_token']

    headers = {'Authorization': cfg['twitter']['oauth']['bearer_token'] }
    response = requests.get(url, headers=headers, params=payload)
    return response.json()

def getRefInfo(referenced_tweet):
    for ref in referenced_tweet:
        # if ref['type'] == 'retweeted':
        tweet = [t for t in referenced_tweets if t["id"] == ref['id'] ][0]
        user = [u for u in users if u["id"] == tweet['author_id'] ][0]
        return {'type': ref['type'], 'username': user}

def parseTweet(tweet):
    # get user Owner
    hasRef = False
    user = [u for u in users if u["id"] == tweet['author_id'] ][0]
    # is RT
    if tweet.get('referenced_tweets'):
        hasRef = True
        ref = getRefInfo(tweet.get('referenced_tweets'))
    if(tweet.get('entities')):
        mentions = list(map(lambda m: m['id'], tweet['entities']['mentions']))
        userMention = [u for u in users if u["id"] in mentions ]
        for u in userMention:
            tweets.append({
                'id' : tweet['id'],
                'text' : tweet['text'],
                'created_at' : parseDate(tweet.get('created_at', None)),
                'screen_name' : user['username'],
                'followers_count' : user['public_metrics']['followers_count'],
                'author_id' : tweet['author_id'],
                'mention' : u['username'],
                'type' : ref['type'] if hasRef else 'tweet',
                'retweet' : (True if ref['type'] == 'retweeted' else False) if hasRef else False,
                'retweet_user' : ref['username']['username'] if hasRef else 'NA'
            })            
    else:
        tweets.append({
            'id' : tweet['id'],
            'text' : tweet['text'],
            'created_at' : parseDate(tweet.get('created_at', None)),
            'screen_name' : user['username'],
            'followers_count' : user['public_metrics']['followers_count'],
            'author_id' : tweet['author_id'],
            'mention' : None,
            'type' : ref['type'] if hasRef else 'tweet',
            'retweet' : (True if ref['type'] == 'retweeted' else False) if hasRef else False,
            'retweet_user' : ref['username']['username'] if hasRef else 'NA'
        })

def processTweets(data):
    # Has expansions
    if data.get('includes'):
        # Has users
        # includes = data.get('includes')
        if data['includes']['users']:
            users.extend(data['includes']['users'])
        # has tweets referenced
        if data['includes']['tweets']:
            referenced_tweets.extend(data['includes']['tweets'])

    for tweet in data['data']:
        ## process Tweet
        if tweet['id'] not in tweet_list_ids:
            tweet_list_ids.append(tweet['id'])
            parseTweet(tweet)

def getTweetsApiWithPagination(query, params, pagination={'size': 0, 'full': False}):
    if pagination['full']:
        # print("process Full")
        res = searchTweets(query, params=params)
        # res = dataTw.res
        processTweets(res)
        while res['meta'].get('next_token'):
            print(f"Length Tws: {len(tweet_list_ids)}")
            if len(tweet_list_ids) > limit_tweets: ## if setted limit of tweets
                break
            params['next_token'] = res['meta'].get('next_token')
            print(f"Last Token API pagination : {params['next_token']}")
            res = searchTweets(query, params=params)
            # res = dataTw.res3
            processTweets(res)
    else:
        # print(f"process N° {pagination['size']} pages")
        for _ in range(pagination['size']): # Specific pagination
            print(f"Length Tws: {len(tweet_list_ids)}")
            res = searchTweets(query, params=params)
            params['next_token'] = res['meta'].get('next_token')
            print(f"Last Token API pagination : {params['next_token']}")            
            processTweets(res)
            if not res['meta'].get('next_token') or len(tweet_list_ids) > limit_tweets:
                break


## SCRAPY METHODS
def searchTweetsScrapy(query, params = {}, max_results=20):
    url = cfg['twitter']['endpoints']['searchCrw']
    payload = {
        'q': query,
        'count': max_results
    }
    # Get Full Text
    if params.get('tweet_mode'):
        payload['tweet_mode'] = params['tweet_mode']
    # Get query_source
    if params.get('query_source'):
        payload['query_source'] = params['query_source']        
    # Get Latest Tweet - Default Top
    if params.get('tweet_search_mode'):
        payload['tweet_search_mode'] = params['tweet_search_mode']
    # Next TOken pagination
    if params.get('cursor'):
        payload['cursor'] = params['cursor']
    headers = cfg['twitter']['scraper']
    response = requests.get(url, headers=headers, params=payload)
    return response.json()

def parseInfoUserScrapy(user):
    if user:
        return {
                    "public_metrics": {
                        "followers_count": user['followers_count'],
                        "following_count": user['friends_count'],
                        "tweet_count": user['statuses_count'],
                        "listed_count": user['listed_count']
                    },
                    "created_at": parseDate(user['created_at']), #format Date
                    "name": user['name'],
                    "id": user['id_str'],
                    "username": user['screen_name']
                },
    return {}

def parseTweetScrapy(tweet, user):
    mentions = tweet['entities']['user_mentions']
    if mentions:
        for m in mentions:
            tweets.append({
                'id' : tweet['id_str'],
                'text' : tweet['full_text'],
                'created_at' : parseDate(tweet.get('created_at', None)),
                'screen_name' : user['username'],
                'followers_count' : user['public_metrics']['followers_count'],
                'author_id' : tweet['user_id_str'],
                'mention' : m['screen_name'],
                'type' : 'tweet', # ref['type'] if hasRef else 'tweet',
                'retweet' : False, # (True if ref['type'] == 'retweeted' else False) if hasRef else False,
                'retweet_user' : 'NA' # ref['username']['username'] if hasRef else 'NA'
            })
    else:
        tweets.append({
                'id' : tweet['id_str'],
                'text' : tweet['full_text'],
                'created_at' : parseDate(tweet.get('created_at', None)),
                'screen_name' : user['username'],
                'followers_count' : user['public_metrics']['followers_count'],
                'author_id' : tweet['user_id_str'],
                'mention' : None,
                'type' : 'tweet', # ref['type'] if hasRef else 'tweet',
                'retweet' : False, # (True if ref['type'] == 'retweeted' else False) if hasRef else False,
                'retweet_user' : 'NA' # ref['username']['username'] if hasRef else 'NA'
            })

def getNextCursosScrapy(timeline):
    entries = timeline['instructions'][0]['addEntries']['entries']
    cursorButtom = [e for e in entries if e["entryId"] == "sq-cursor-bottom" ]
    if cursorButtom:
        cursor = cursorButtom[0]['content']['operation']['cursor']['value']
        return cursor
    else:
        try:
            replaceEntry = timeline['instructions'][2]
            cursor = replaceEntry['replaceEntry']['entry']['content']['operation']['cursor']['value']
            return cursor
        except:
            return '-1'

def processScrapy(data):
    tweets = data['globalObjects']['tweets']
    usersScrapy = data['globalObjects']['users']
    for k,t in tweets.items():
        ## add keys no repit
        if k not in tweet_list_ids:
            tweet_list_ids.append(k)
            user = parseInfoUserScrapy(next((v for k, v in usersScrapy.items() if k == t['user_id_str']), None))
            users.append(user[0]) ## add user to list
            # print(f"Key: {k}, \nTweet: {t}, \nuser: {user}")
            parseTweetScrapy(t, user[0])

def getTweetsScrapyWithPagination(query, params, pagination={'size': 0, 'full' : False}, latest= False):
    if latest: # Get new tweets, default Top
        params['tweet_search_mode'] = 'live'
    if pagination['full']:
        res = searchTweetsScrapy(query, params)
        # res = dataTw.resScrapy
        processScrapy(res)
        while res['globalObjects']['tweets']:
            print(f"Length Tws: {len(tweet_list_ids)}")
            if len(tweet_list_ids) > limit_tweets: ## if setted limit of tweets
                break
            params['cursor'] = getNextCursosScrapy(res['timeline'])
            print(f"Last SCRAPY cursor pagination : {params['cursor']}")
            if params['cursor'] == '-1': # validate no more cursor scroll
                break
            res = searchTweetsScrapy(query, params=params)
            # res = dataTw.resScrapy
            processScrapy(res)
    else:
        # print(f"process Scrapy N° {pagination['size']} pages")
        for _ in range(pagination['size']): # Specific pagination
            print(f"Length Tws: {len(tweet_list_ids)}")
            res = searchTweetsScrapy(query, params=params)
            # res = dataTw.resScrapy
            params['cursor'] = getNextCursosScrapy(res['timeline'])
            print(f"Last SCRAPY cursor pagination : {params['cursor']}")            
            processScrapy(res)
            if not res['globalObjects']['tweets'] or len(tweet_list_ids) > limit_tweets:
                break


#RECOVER FRENDS METHODS
def getFriendsIds(user, count=5000, cursor=-1):
    url = cfg['twitter']['endpoints']['friendsIds']
    # headers = {'Authorization': cfg['twitter']['oauth']['bearer_token'] }
    headers = {'Authorization': random.choice(rnd_tokens) }
    params = {
        'screen_name': user,
        'count': count,
        'cursor': cursor
    }
    response = requests.request("GET", url, headers=headers, params=params)
    return response.json()

def getAllFriends(user, cursor, n_friends, counter):
    global num_req_friends
    friends_ids = []
    ids_count = 0
    
    while (cursor != 0) and (ids_count < n_friends):
        try:
            num_req_friends  = num_req_friends + 1
            sleepProcess((num_req_friends % (len(rnd_tokens)*13) == 0), 900) # sleep process by Rate limited friends endpoint (15min)
            # res = dataTw.resFriends
            res = getFriendsIds(user, 5000, cursor)
            friends_ids = friends_ids + res['ids']
            cursor = res['next_cursor']
            ids_count += len(res['ids'])
            friends_ids = list(set(friends_ids))
            friends_ids.sort()
        except:
            print("Error request!")
            sleepProcess((5 % 5 == 0), 60) # sleep process by Rate limited friends endpoint (15min)
            pass
    return friends_ids
            
def processUserFriends(df):
    counter = 0
    uniqueUsers = getAllUniqueUser(df)
    print(f"Unique user to process: {len(uniqueUsers)}")
    for screen_name in uniqueUsers:
        # print(screen_name)
        item = db.friends.find_one({"screen_name": screen_name})
        if item is None:
            counter =  counter + 1
            ids = getAllFriends(screen_name, -1, 10000, counter)
            item = {"screen_name": screen_name, "ids" : ids}
            insertDb(db.friends, item, True)

# GRAPH METHODS
def processGraph(df):
    fullUsers = getAllUniqueUser(df)
    print(fullUsers)
    # G.add_nodes_from(df['screen_name'].tolist())
    G.add_nodes_from(fullUsers)
    nx.set_node_attributes(
        G,        
        dict(zip(df['screen_name'].tolist(), df['followers_count'].tolist())),
        'followers',
    )

    for index, row in df.iterrows():
        node = row['screen_name']
        if row['retweet']: # si es RT, se agrega un loop
            # G.add_edge(node, node)
            G.add_edge(node, row['retweet_user'])
        # else: #si no es RT, se ve si hay mención. Si la hay, se añade enlace por cada mención.
            # if pd.notnull(row['mention']):
        if row['mention']:
            # if (row['mention'] in df['screen_name'].tolist()): #solo si la mención es a un usuario del grupo de control.
                # G.add_edge(node, row['mention'])
            G.add_edge(node, row['mention'])

    for index, row in df.iterrows():
        friends = db.friends.find_one({"screen_name": row['screen_name']})
            
        try:
            for u, v in df.iterrows():
                if v['author_id'] in friends['ids']:
                    G.add_edge(row['screen_name'], v['screen_name'])
        except:
            pass

    """ myZip = zip(df['screen_name'].tolist(), df['followers_count'].tolist())
    print(f"miZip: {myZip} ")
    print(f"miDict: {dict(myZip)} ") """
    print(len(G.nodes()))

    # Draw and Save graph as image
    nx.draw(G, with_labels=True)
    # plt.show() 
    plt.savefig("path.png") # to save
    nx.write_graphml(G, "test.graphml")


def main():
    ## EXTRACT TWEETS
    # Api
    getTweetsApiWithPagination(query, params=searchParams, pagination={'size': -1, 'full':True})
    # getTweetsWithPagination(query, params=searchParams, pagination={'size': 2, 'full':False}) # with limit pagination
    print(f"Total extracted TWs API: {len(tweet_list_ids)} \nWith user list: {len(users)}")

    # Scrapy
    # Top
    getTweetsScrapyWithPagination(query, params=searchScrapyParams, pagination={'size': -1, 'full':True}, latest=False)
    print(f"Total extracted TWs SCRAPY Top: {len(tweet_list_ids)} \nWith user list: {len(users)}")
    # Latest
    getTweetsScrapyWithPagination(query, params=searchScrapyParams, pagination={'size': -1, 'full':True}, latest=True)
    print(f"Total extracted TWs SCRAPY Latest: {len(tweet_list_ids)} \nWith user list: {len(users)}")
    
    ## SAVE Tw Csv & Db
    print("Saving Tweets en Csv and Database...")
    dft = convertDfAndExport(tweets, '/home/g30v4/Desktop/tweets.csv')
    insertDb(db.tweets, tweets, False)
    print(dft.sample(15)) # get sample

    ## SAVE Users Csv & Db
    print("Saving Users Tweets en Csv and Database...")
    dfu = convertDfAndExport(users, '/home/g30v4/Desktop/users.csv')
    insertDb(db.users, users, False)
    print(dfu.sample(15)) # get sample
    
    ## LOAD Tweets
    # dft = loadDataFrame('/home/g30v4/Desktop/tweets.csv')
    
    ## EXTRACT Friends
    print("Extracted friends all Unique Users...")
    processUserFriends(dft)

    ## GENERATE Graph
    print("Generating graph...")
    processGraph(dft)


main()