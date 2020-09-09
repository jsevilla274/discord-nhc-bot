# nhclib
# A simple library that makes synchronous requests to various NHC RSS feeds for
# cyclone data. Intended for use with NHC Storm Tracker Discord Bot.
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
import re
import datetime 
import pytz

# NHC Timezones converted to Olson tz format
NHC_TIMEZONES = {'HI' : 'Pacific/Honolulu', 'AK': 'America/Anchorage', 
    'PST': 'America/Los_Angeles', 'PDT': 'America/Los_Angeles',
    'MST': 'America/Denver', 'MDT': 'America/Denver',
    'CST': 'America/Chicago', 'CDT': 'America/Chicago',
    'EST': 'America/New_York', 'EDT': 'America/New_York',
    'AST': 'America/Puerto_Rico', 'Guam': 'Pacific/Guam',
    'CVT': 'Atlantic/Cape_Verde'}

# checks if URL is valid by making HEAD request
def isValidURL(url):
    req = urllib.request.Request(url, method='HEAD')
    try:
        response = urllib.request.urlopen(req)
        if response.status == 200:
            return True
        else:
            print('WARNING: Response status ', response.status)
            return False
    except urllib.error.HTTPError as e:
        print('The server couldn\'t fulfill the request.')
        print('Error code: ', e.code)
        return False
    except urllib.error.URLError as e:
        print('We failed to reach a server.')
        print('Reason: ', e.reason)
        return False

# Issues a GET request to the url with the given headers (hdrs)
# Returns an http.client.HTTPResponse object on status 200, or None otherwise
def getResponseFromURL(url, hdrs=None):
    try:
        if hdrs:
            req = urllib.request.Request(url, headers=hdrs)
            response = urllib.request.urlopen(req)
        else:
            response = urllib.request.urlopen(url)

        if response.status == 200:
            return response
        else:
            print('WARNING: Response status ', response.status)
            return None
    except urllib.error.HTTPError as e:
        print('The server couldn\'t fulfill the request.')
        print('Error code: ', e.code)
        return None
    except urllib.error.URLError as e:
        print('We failed to reach a server.')
        print('Reason: ', e.reason)
        return None

# Retrieves cyclone data from one of the NHC's Basin-wide Tropical Cyclone
# XML feeds. Data is obtained from an RSS feed URL (basinURL) and is populated
# into a list of storms (cyclones) as a dictionary with specific properties.
# Types of storms to track can be specified (trackTypes) although tracks all
# cyclone types by default. A list of cyclone ATCFs to avoid can be supplied as 
# well (blacklist). You can also narrow the search of one cyclone by specifying
# its name (find), though in this case it is recommended to not pass trackTypes
# or a blacklist to broaden the search
#
# Returns 1 if successfully updated cyclones and -1 otherwise
def updateCyclonesFromBasin(cyclones, basinURL, trackTypes=[], blacklist=[], find=''):
    for cType in trackTypes:
        cType = cType.lower()

    response = getResponseFromURL(basinURL)
    if response is None:
        return -1
    XMLstring = response.read().decode('utf-8')
    root = ET.fromstring(XMLstring)

    # for each cyclone, obtain its details
    ns = {'nhc': 'https://www.nhc.noaa.gov'}
    cycElems = root.findall('.//nhc:Cyclone', ns)
    if len(cycElems) < 1:
        print('There are no tropical cyclones in the Atlantic Basin at this time')
        return -1

    for cycElem in cycElems:
        cyclone = {}
            
        # get cyclone ATCF
        cycloneATCF = cycElem.find('nhc:atcf', ns)
        if cycloneATCF is None:
            print('ERROR: Cyclone atcf not found!')
            continue # skip this cyclone
        else:
            cyclone['atcf'] = cycloneATCF.text
            reject = False
            # check if cyclone already tracked
            for c in cyclones:
                if c['atcf'] == cyclone['atcf']:
                    print('INFO: Cyclone ' + cyclone['atcf'] + ' is already tracked')
                    reject = True
                    break
            # check if cyclone not in blacklist
            if cyclone['atcf'] in blacklist:
                print('INFO: Cyclone ' + cyclone['atcf'] + ' is blacklisted')
                reject = True
            
            if reject:
                continue # skip this cyclone

        # get cyclone name
        cycloneName = cycElem.find('nhc:name', ns)
        if cycloneName is None:
            print('ERROR: Cyclone name not found!')
            continue # skip this cyclone
        elif find and find != cycloneName.text.lower():
            print('INFO: Cyclone name does not match "' + find + '" , skipping cyclone')
            continue # skip this cyclone
        else:
            cyclone['name'] = cycloneName.text.lower()
            print('INFO: Cyclone {0} is named {1}'.format(cyclone['atcf'], cyclone['name'].capitalize()))

        # check if cyclone is of interest (within desired types)
        cycloneType = cycElem.find('nhc:type', ns)
        if cycloneType is None:
            print('ERROR: Type of Cyclone ' + cyclone['atcf'] + ' not found!')
            continue # skip this cyclone
        elif len(trackTypes) > 0 and cycloneType.text.lower() not in trackTypes:
            print('INFO: Cyclone ' + cyclone['atcf'] + '\'s strength too low!')
            continue # skip this cyclone

        # check if wallet id gives valid advisory URL
        walletID = cycElem.find('nhc:wallet', ns)
        if walletID is None:
            print('ERROR: Wallet ID of Cyclone ' + cyclone['atcf'] + ' not found!')
            continue # skip this cyclone

        advisoryURL = 'https://www.nhc.noaa.gov/xml/TCP' + walletID.text + '.xml'
        if isValidURL(advisoryURL):
            cyclone['advisoryurl'] = advisoryURL
            print('SUCCESS: Advisory URL of Cyclone ' + cyclone['atcf'] + ' is valid!')
        else:
            print('ERROR: Advisory URL of Cyclone ' + cyclone['atcf'] + ' is invalid!')
            continue # skip this cyclone

        # get cyclone graphic URL
        graphicsTitle = '{0} {1} Graphics'.format(cycloneType.text, cyclone['name'])
        foundGraphic = False
        for item in root.findall('.//item'):
            title = item.find('title')
            if title is None:
                continue # skip item
            
            if graphicsTitle.lower() in title.text.lower():
                # first link in <description> should be the best graphic
                match = re.search(r'(?:http\:|https\:)?\/\/.*\.png', 
                    item.find('description').text)

                if match:
                    # get large version of png (remove '_sm2')
                    cycloneImgURL = re.sub('_sm2', '', match.group(0))

                    if isValidURL(cycloneImgURL):
                        foundGraphic = True
                        print('SUCCESS: Image URL of Cyclone ' + cyclone['atcf'] + ' is valid!')
                        cyclone['imgurl'] = cycloneImgURL
                    else:
                        print('ERROR: Image URL of Cyclone ' + cyclone['atcf'] + ' is invalid!')
                else:
                    print('ERROR: Image URL of Cyclone ' + cyclone['atcf'] + ' not found!')

                break # graphics section found; exit item loop
            # else did not match graphicsTitle to the title
        if not foundGraphic:
            continue # skip this cyclone

        # if cyclone not skipped, track the cyclone
        cyclones.append(cyclone)
        print('SUCCESS: Cyclone '+ cyclone['atcf'] + ' appended to \'cyclones\'')

    # return success
    return 1

# Parse text (description) for next advisory messages in the format 
# "Next <adjective> advisory at HHMM AM/PM"
#
# Returns a list of partitioned advisory messages
def nextAdvisories(description):
    newAdvisories = []
    rawAdvisories = re.findall(r'(Next \w+ advisory at) (\d+ \w+) (\w+)', 
        description)
    if rawAdvisories: # advisory data found
        for adv in rawAdvisories:
            advisory = {}
            advisory['message'] = adv[0]
            advisory['time'] = adv[1]
            advisory['timezone'] = adv[2]

            newAdvisories.append(advisory)
    else:
        print('ERROR: Failed to parse advisories from description!')
    return newAdvisories

# Retrieves a datetime for a given NHC advisory with correct timezone using the 
# current datetime as a base.
# NOTE: Assumes advisory is in the future and within 24 hours of the current 
# time to calculate the correct day
#
# Returns a localized datetime object of the given advisory
def datetimeFromAdvisory(advisory):
    advisoryTimeRaw = advisory['time']
    advisoryTZRaw = advisory['timezone'].upper()
    if advisoryTZRaw in NHC_TIMEZONES:
        advisoryTZ = NHC_TIMEZONES[advisoryTZRaw]
    else:
        print('ERROR: Could not convert NHC timezone "' + advisoryTZRaw + '"to Olson tz format')
        return None
    
    if len(advisoryTimeRaw) < 4:
        # prepend '0' for strptime processing
        advisoryTimeRaw = '0' + advisoryTimeRaw

    # create advisoryTime based off current day
    currentTime = datetime.datetime.now(pytz.timezone(advisoryTZ))
    year = str(currentTime.year)

    if currentTime.day < 10:
        day = '0' + str(currentTime.day)
    else:
        day = str(currentTime.day)

    if currentTime.month < 10:
        month = '0' + str(currentTime.month)
    else:
        month = str(currentTime.month)

    advisoryTimeRaw = '{0} {1} {2} {3}'.format(day, month,  year, advisoryTimeRaw)
    advisoryTime = datetime.datetime.strptime(advisoryTimeRaw, '%d %m %Y %I%M %p')
    advisoryTime = pytz.timezone(advisoryTZ).localize(advisoryTime)

    # if next advisory crosses into next day, adjust day by 1 (see: NOTE above)
    if currentTime.hour > advisoryTime.hour:
        advisoryTime += datetime.timedelta(days=1) 
    return advisoryTime

# Updates the 'updatetime', 'nextadvisory', 'advisorytitle', and 'advisorymsg' 
# properties of a given (cyclone). Can also optionally update the 'name' property
# (updateName) of a cyclone if it's name can change (such as when tracking 
# 'unnamed' cyclones)
# If the update failed at any point, one or more of these properties will be falsy
def updateCyclone(cyclone, updateName=False):
    if 'updatetime' in cyclone: # has a last updated time
        response = getResponseFromURL(cyclone['advisoryurl'], 
            hdrs={'If-Modified-Since': cyclone['updatetime']})
    else:
        response = getResponseFromURL(cyclone['advisoryurl'])

    cyclone['nextadvisory'] = None
    cyclone['advisorytitle'] = ''
    cyclone['advisorymsg'] = ''
    if response: # an XML with new cyclone data obtained
        cyclone['updatetime'] = response.getheader('last-modified')
        XMLstring = response.read().decode('utf-8')
        root = ET.fromstring(XMLstring)

        # get advisory title
        titleElem = root.find('.//title')
        if titleElem is None:
            print('ERROR: Title not found in Cyclone ' + cyclone['atcf'] + '\'s advisory')
        else:
            # infer the cyclone's name from the title
            if updateName:
                r = re.compile(r'(\w+) (Intermediate|Public)', flags=re.I)
                matches = r.findall(titleElem.text)
                if len(matches) > 0:
                    cyclone['name'] = matches[0][0].lower()
            cyclone['advisorytitle'] = titleElem.text

        # get future advisory time
        descElem = root.find('.//item/description')
        if descElem is None:
            print('ERROR: Description not found in Cyclone ' + cyclone['atcf'] + '\'s advisory')
        else:
            nAdvisories = nextAdvisories(descElem.text)
            if nAdvisories:
                # assume the first advisory found is the soonest
                cyclone['nextadvisory'] = datetimeFromAdvisory(nAdvisories[0])
                cyclone['advisorymsg'] = nAdvisories[0]['message']
    else:
        print('ERROR: Unable to retrieve Cyclone ' + cyclone['atcf'] + '\'s latest advisory')