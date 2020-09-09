# NHC Storm Tracker Discord Bot
#
# A bot that periodically polls the National Hurricane Center's Atlantic Basin 
# RSS feed for cyclone data and makes posts on a Discord server with this data.
# NOTE: Currently only supports reporting storm data in one channel, so
# attempting to use on multiple servers will cause errors.
import discord
import nhclib
import datetime
import pytz
import asyncio
from discord.ext import commands

bot = commands.Bot(command_prefix='!')
NHC_Channel = -1
TrackedCyclones = []
BlacklistedCyclones = []
CYCLONE_STRENGTHS = ['tropical storm', 'hurricane']
BASIN_URL = 'https://www.nhc.noaa.gov/index-at.xml' # Atlantic Basin
LOCAL_TZ = 'America/New_York'

# Periodically checks for advisory updates on the given cyclone. Sleeps until
# the next advisory occurs, or if an update fails, for 60 seconds to attempt
# another update
async def nhcUpdateCyclone(cyclone, ignoreStrength=False):
    ttl = 10 # "time to live", number of times cyclone will attempt 
             # to update after failure before being automatically removed
    nextUpdateSecs = 0
    while not bot.is_closed() and ttl > 0:
        try:
            await asyncio.sleep(nextUpdateSecs)
        except asyncio.CancelledError:
            print('Cyclone ' + cyclone['atcf'] + '\'s task manually cancelled.')
            TrackedCyclones.remove(cyclone)
            return # exit task function immediately
        
        nextUpdateSecs = 60
        # NOTE: in the event we ignore strength, there is a good chance that the
        # user is adding an "unnamed" storm, and so updates to the name field
        # should be considered
        nhclib.updateCyclone(cyclone, updateName=ignoreStrength) 
        if cyclone['nextadvisory'] and cyclone['advisorytitle']: # failed update gives cyclone falsy properties
            # create a formatted discord post
            nextAdvTime = cyclone['nextadvisory'].astimezone(pytz.timezone(LOCAL_TZ))
            nextAdvTimeStr = datetime.datetime.strftime(nextAdvTime, '%I:%M %p')
            formattedPost = '**{0}**\n{1}\n{2} {3}'.format(cyclone['advisorytitle'], 
                cyclone['imgurl'], cyclone['advisorymsg'], nextAdvTimeStr)
                
            # Send the post to the NHC channel
            await bot.get_channel(NHC_Channel).send(formattedPost)

            # if cyclone strength is still worth tracking (in CYCLONE_STRENGTHS)
            if ignoreStrength or any(cStrength in cyclone['advisorytitle'].lower() for cStrength in CYCLONE_STRENGTHS):
                # calculate sleep time
                currentTime = datetime.datetime.now(pytz.timezone(LOCAL_TZ))
                diff = (nextAdvTime - currentTime).total_seconds()
                if diff > 0:
                    nextUpdateSecs = diff
                    ttl = 10
                else:
                    print('ERROR: Difference between next advisory and current time is negative!')
                    ttl -= 1
            else:
                print('Cyclone ' + cyclone['atcf'] + ' is no longer of interest, untracking.')
                ttl = 0 
        else:
            ttl -= 1
            print('ERROR: Failed to update Cylone {0}, retrying in {1} seconds'.format(cyclone['atcf'], nextUpdateSecs))

    # remove cyclone from memory
    print('No longer tracking Cyclone ' + cyclone['atcf'])
    TrackedCyclones.remove(cyclone)
        

# Scans the NHC's Atlantic Basin RSS feed every 6 hours (21600 s) and adds them to 
# the list of TrackedCyclones. If new cyclones are found, tasks are created
# for them so they update automatically. Additionally clears the blacklist of
# cyclone IDs (or ATCFs) approximately every week (6hr * 30)
async def nhcScanBasin():
    blacklistPurge = 0
    while not bot.is_closed():
        if blacklistPurge > 30:
            BlacklistedCyclones = []
        blacklistPurge += 1

        # get cyclones from basin
        nhclib.updateCyclonesFromBasin(TrackedCyclones, BASIN_URL, 
            CYCLONE_STRENGTHS, BlacklistedCyclones)
        for cyclone in TrackedCyclones:
            if 'task' not in cyclone:
                # non-tracked cyclone -> track it
                cyclone['task'] = bot.loop.create_task(nhcUpdateCyclone(cyclone))
        time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print('Atlantic Basin updated at ' + time)
        await asyncio.sleep(21600) # sleep for 6 hours

# Sends a "help" post in the given discord context (ctx) which details
# various commands and functionality of the storm tracker
async def nhcDisplayHelp(ctx):
    post = '**National Hurricane Center Storm Tracker**\n'\
        'Scans the NHC\'s Atlantic Basin feed every 6 hours and '\
        'automatically tracks any active storms found\n'\
        '`!nhc` - displays this help prompt\n'\
        '`!nhc track <storm name>` - manually tracks storm (if not tracked '\
        'already) and subscribes you to advisory updates for it\n'\
        '`!nhc untrack <storm name>` - manually untracks storm'\
        '`!nhc init` - moves storm updates to the channel this command was sent in'
    await ctx.send(post)

@bot.event
async def on_ready():
    print('Bot logged in as {0.user}'.format(bot))
    # Subscribes the first text channel of the first guild to receive NHC updates
    global NHC_Channel 
    NHC_Channel = bot.guilds[0].text_channels[0].id
    bot.loop.create_task(nhcScanBasin())

@bot.command()
async def nhc(ctx, *args):
    if len(args) > 0:
        subCommand = args[0].lower()
        if subCommand == 'track':
            cycloneName = args[1].lower()

            # check if storm not already tracked
            for cyclone in TrackedCyclones:
                if cyclone['name'] == cycloneName:
                    await ctx.send('Cyclone ' + cyclone['name'] + ' already tracked!')
                    return # do not process further

            trackSuccess = False
            # NOTE: Not specifying strengths or blacklist when "finding" cyclone
            nhclib.updateCyclonesFromBasin(TrackedCyclones, BASIN_URL, find=cycloneName)
            for cyclone in TrackedCyclones:
                if 'task' not in cyclone:
                    trackSuccess = True
                    # remove from blacklist if necessary
                    if cyclone['atcf'] in BlacklistedCyclones:
                        BlacklistedCyclones.remove(cyclone['atcf'])

                    # create task for it
                    cyclone['task'] = bot.loop.create_task(nhcUpdateCyclone(cyclone, ignoreStrength=True))
                    break # break out of cyclone loop
                
            if not trackSuccess:
                await ctx.send('Could not find "' + args[1] + '" in the Atlantic Basin')
        elif subCommand == 'untrack':
            cycloneName = args[1].lower()
            untrackSuccess = False
            for cyclone in TrackedCyclones:
                if cyclone['name'] == cycloneName:
                    untrackSuccess = True
                    BlacklistedCyclones.append(cyclone['atcf']) # blacklist cyclone
                    cyclone['task'].cancel() # cancel the associated task
                    break # break out of cyclone loop

            if untrackSuccess:
                await ctx.send('Cyclone ' + cycloneName.capitalize() + ' has been untracked')
            else:
                await ctx.send('Could not find "' + args[1] + '"')
        elif subCommand == 'init':
            global NHC_Channel 
            NHC_Channel = ctx.message.channel.id
            await ctx.send('NHC Storm Tracker updates will now be sent to this channel')
        elif subCommand == 'debug':
            post = 'Cyclones: {0}\nBlacklist: {1}'.format(str(TrackedCyclones), 
                str(BlacklistedCyclones))
            await ctx.send(post)
        else:
            await nhcDisplayHelp(ctx)
    else:
        await nhcDisplayHelp(ctx)

bot.run('')