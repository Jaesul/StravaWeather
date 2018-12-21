import urllib, urllib2, webbrowser, json
import jinja2
from google.appengine.api import urlfetch
from google.appengine.ext import db
import logging
import os
import logging
import time
import webapp2
from secrets import STRAVA_APP_CLIENT_ID
from secrets import STRAVA_APP_SECRET
from secrets import DARKSKY_TOKEN
from secrets import FLICKR_KEY

def pretty(obj):
    return json.dumps(obj, sort_keys=True, indent=2)

# Gets the json data from the url
def safeGet(url):
    return urllib2.urlopen(url)

# Setting up jinja
JINJA_ENVIRONMENT = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

# Returns the weather data of the specified lat lng
def lookupweather(lat,lng):
    baseurl = "https://api.darksky.net/forecast/"
    url = "%s%s/%s,%s"%(baseurl,DARKSKY_TOKEN,lat,lng)
    print("fetching %s"%url)
    return json.load(safeGet(url))

# Method that calls json data
def flickrREST(baseurl = 'https://api.flickr.com/services/rest/',
    method = 'flickr.photos.search',
    api_key = FLICKR_KEY,
    format = 'json',
    params={},
    printurl = False
    ):
    params['method'] = method
    params['api_key'] = api_key
    params['format'] = format
    if format == "json": params["nojsoncallback"]=True
    url = baseurl + "?" + urllib.urlencode(params)
    if printurl:
        print(url)
    return safeGet(url)

# Gets the photo id's for a given tag
def getPhotoIDs(tag, n = 2):
    data = flickrREST(params = {'tags': tag, 'per_page' : n})
    photoids = []
    data = json.load(data)
    for item in data['photos']['photo']:
        photoids.append(item['id'])
    return photoids

# Returns additional info of given photo id
def getPhotoInfo(photoid):
    data = flickrREST(method='flickr.photos.getInfo' ,params={'photo_id': photoid})
    return json.load(data)

# Creates a photo object and keeps data from photo id
class Photo():
    def __init__(self, photoData):
        photoData = photoData['photo']
        self.title = photoData['title']['_content']
        self.author = photoData['owner']['username']
        self.userid = photoData['owner']['nsid']
        tagsData = []
        for thing in photoData['tags']['tag']:
          tagsData.append(thing['_content'])
        self.tags = tagsData
        self.commentcounts = photoData['comments']['_content']
        self.numViews = photoData['views']
        self.url = photoData['urls']['url'][0]['_content']
        farmid = photoData['farm']
        serverid = photoData['server']
        id = photoData['id']
        secret = photoData['secret']
        self.thumbnailURL = "https://farm" + str(farmid) + ".staticflickr.com/" + str(serverid) + "/" + str(id) + "_" + str(secret) + "_q.jpg"

    def __str__(self):
        return '~~~ %s ~~~\nnumber of tags: %s\nviews %s\ncomments %s'%(self.author,len(self.tags),self.numViews,self.commentcounts)

    def viewCountvalue(self):
        return self.numViews

# Google database model that stores information on the user
class User(db.Model):
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)
    access_token = db.StringProperty(required=True)
    uid = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    id = db.StringProperty(required=True)

# Choses the top viewed photo based on number of views
def getTopViewed(tag):
    collection = getPhotoIDs(tag, 2)
    data = [Photo(getPhotoInfo(x)) for x in collection]
    def returnVewCount(obj):
        return int(obj.numViews)
    a = sorted(data, key=returnVewCount, reverse=True)
    return a[0]

# Main handler of the website, bug where going to the stravahandler goes back to the mainhandler
class MainHandler(webapp2.RequestHandler):
    def get(self):
        args = {}
        template = JINJA_ENVIRONMENT.get_template('StravaLogin.html')
        self.response.write(template.render(args))

    def post(self):
        logging.info('this is a post')
        user_all = User.all()
        user_all.filter('id =', 'user')
        user = user_all[0]
        search_input = self.request.get('search_input')
        vals = {}
        vals['name'] = (user.name).upper()
        if search_input:
            access_token = user.access_token
            # Gets the ride data and sets end and start ride location
            data = getRideData(search_input, access_token)
            slat = data['start_latitude']
            slng = data['start_longitude']
            elat = data['end_latlng'][0]
            elng = data['end_latlng'][1]

            # Gets the weather data of the start and end location
            start_weather_data = lookupweather(slat, slng)
            end_weather_data = lookupweather(elat, elng)
            start_weather = start_weather_data['currently']['summary']
            end_weather = end_weather_data['currently']['summary']
            start_temp = start_weather_data['currently']['temperature']
            end_temp = end_weather_data['currently']['temperature']

            # Gets the photos of the weather
            start_weather_Photo = getTopViewed(start_weather)
            end_weather_Photo = getTopViewed(end_weather)
            vals['start_weather_Photo_url'] = start_weather_Photo.thumbnailURL
            vals['end_weather_Photo_url'] = end_weather_Photo.thumbnailURL
            vals['s_temp'] = start_temp
            vals['e_temp'] = end_temp
            vals['s_weather'] = start_weather
            vals['e_weather'] = end_weather

            # Outputs the data to a jinja template
            template = JINJA_ENVIRONMENT.get_template('StravaResults.html')
            self.response.write(template.render(vals))
        else:
            vals['error'] = 'Can\'t get ride data without ride ID'
            template = JINJA_ENVIRONMENT.get_template('StravaTemplate.html')
            self.response.write(template.render(vals))

# Logs in the user through strava, gets the verification code and stores the token
class LoginHandler(webapp2.RequestHandler):
    def get(self):
        args = {'client_id': STRAVA_APP_CLIENT_ID}
        verification_code = self.request.get("code")
        if verification_code:
            user_verification_data = json.loads(getToken(verification_code))
            firstname = user_verification_data['athlete']['firstname']
            uid = user_verification_data['athlete']['id']
            access_token = user_verification_data['access_token']
            user = User(key_name=str(uid), uid=str(uid), name=str(firstname), access_token=str(access_token), id='user')
            user.put()
            user_all = User.all()
            user_all.filter('id =', 'user')
            user = user_all[0]
            args['name'] = firstname
            template = JINJA_ENVIRONMENT.get_template('StravaTemplate.html')
            self.response.write(template.render(args))
        else:
            # not logged in yet-- send the user to Strava to do that
            args['redirect_uri'] = self.request.path_url
            args["scope"] = "activity:read_all,profile:read_all"
            args['client_id'] = STRAVA_APP_CLIENT_ID
            args['response_type'] = 'code'
            url = "https://www.strava.com/oauth/authorize?" + urllib.urlencode(args)
            self.redirect(url)

class StravaResultsHandler(webapp2.RequestHandler):
    def post(self):
        logging.info('this is a post')
        user = User.all()
        user.filter('id =', 'user')
        search_input = self.request.get('ride_id')
        vals = {}
        vals['error'] = 'error'
        if search_input:
            access_token = user.access_token
            data = json.loads(getRideData(str(search_input), access_token))
            slat = data['start_latitude']
            slong = data['start_longitude']
            elat = data['end_latlng']['0']
            elong = data['end_latlng']['1']
            vals['data'] = pretty(data)
            vals['ride_id'] = search_input
            template = JINJA_ENVIRONMENT.get_template('StravaResults.html')
            self.response.write(template.render(vals))
        else:
            vals['error'] = 'cannot get ride data without ride id'
            template = JINJA_ENVIRONMENT.get_template('StravaTemplate.html')
            self.response.write(template.render(vals))

# Does not work
class LogoutHandler(webapp2.RequestHandler):
    def get(self):
        self.redirect("/")

# Exchanges the verification code for a user based token
def getToken(code):
    token_url = 'https://www.strava.com/oauth/token?'
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    token_url_payload = {'grant_type': 'authorization_code', 'client_id': STRAVA_APP_CLIENT_ID, 'client_secret': STRAVA_APP_SECRET, 'code':code}
    data = urllib.urlencode(token_url_payload)
    response = urlfetch.fetch(url=token_url, payload=data, method=urlfetch.POST, headers=headers)
    return response.content

# Returns the json data of the given ride id 
def getRideData(rideID, accessToken):
    url = 'https://www.strava.com/api/v3/activities/' + str(rideID)
    headers = {'Authorization': 'Bearer ' + accessToken}
    params = None
    response = urlfetch.fetch(url, method=urlfetch.GET, payload=params, headers=headers)
    return json.loads(response.content)
    # return json.load(safeGet(url))

application = webapp2.WSGIApplication([ \
     ("/login", LoginHandler), ('/.*', MainHandler),
    ('/stravaresults', StravaResultsHandler)
],
    debug=True)
