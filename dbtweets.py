#! python3
# coding: utf-8

import json
import logging
import os
import time
from collections import deque

import requests
import schedule
import tweepy

__version__ = "1.2.5"

# File and directory names
CONFIG_FILE = "config.json"
IMG_DIR = "img"
RECENT_IDS_FILE = "recentids.txt"
DB_DUMP_FILE = "danbooru_dump.txt"

# Templates
DB_URL = "http://danbooru.donmai.us/"
DB_API_URL = DB_URL + "{endpoint}.json{params}"
PIXIV_URL = "http://www.pixiv.net/member_illust.php?mode=medium&illust_id={id}"
DA_URL = "http://{artist}.deviantart.com/gallery/#/{id}"
LOG_FMT = "%(levelname)s (%(name)s): %(message)s"

# Preset tag blacklist, mostly tags that are too explicit
TAG_BLACKLIST = (
    "pregnant",
    "diaper",
    "inflation",
    "panties",
    "guro",
    "scat",
    "peeing",
    "comic",
    "bikini",
    "chastity_belt",
    "trefoil",
    "undressing",
    "spread_legs",
    "pussy",
    "nipples",
    "censored",
    "cum",
    "nude",
    "sex",
    "facial",
    "vaginal",
    "cum_on_body",
    "convenient_censoring",
    "bottomless",
    "covering_breasts",
    "groin",
    "cameltoe",
    "panty_lift",
    "french_kiss",
    "underboob",
    "between_breasts",
    "lingerie",
    "ebola",
    "navel_cutout",
    "partially_visible_vulva",
    "ball_gag",
    "bdsm",
    "bondage",
    "gag",
    "gagged",
    "spoilers",
    "penis",
    "disembodied_penis")
# Usually list of usernames who don't want their art reposted
USER_BLACKLIST = (
    "khee",
    "bakakhee",
    "cactuskhee",
    "junkhee")
# Use for source URLs
# (except Twitter, Pixiv, and deviantart.net, which are processed separately)
SOURCE_DOMAINS = (
    "tumblr.com",
    "deviantart.com",
    "twitpic.com",
    "seiga.nicovideo.jp")
# Use for verifying content type before downloading an image
ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif",
    "binary/octet-stream")
# Post ID number of "TrainerTrish" art
TRISH_ID = 2575437

logger = logging.getLogger(__name__)
config_dict = {}
# For debugging purposes
db_request_raw = ""

class ImageQueue():
    def __init__(self):
        self._items = []

    def enqueue(self, post_id: str, image_uri: str, source: str=None):
        item = (str(post_id), image_uri, source)
        self._items.insert(0, item)

    def dequeue(self):
        return self._items.pop()

    def __len__(self):
        return self._items.__len__()

    def __str__(self):
        return self._items.__str__()

    def is_empty(self):
        return self.__len__() < 1

    def get_first_item(self):
        return self._items[-1] if self._items else None

class TweetPicBot():
    def __init__(self, keys: dict):
        auth = tweepy.OAuthHandler(keys["consumer"], keys["consumer_secret"])
        auth.set_access_token(keys["access"], keys["access_secret"])
        self._api = tweepy.API(auth)
        self._authenticate()

    def _authenticate(self):
        try:
            user = self._api.verify_credentials().screen_name
            logger.info(
                "Twitter API keys verified successfully, authenticated as @%s",
                user)
        except tweepy.TweepError as t:
            log_tweepy_err(t, "Can't verify Twitter API keys")
            raise SystemExit

    def send_tweet(self, media_path: str, tweet=""):
        # Return True if tweet was sent successfully, otherwise False
        try:
            logger.debug("Uploading %s", media_path)
            media_id = self._api.media_upload(media_path).media_id_string

            logger.debug("Sending tweet")
            self._api.update_status(status=tweet, media_ids=[media_id])
            return True
        except tweepy.TweepError as t:
            log_tweepy_err(t, "Failed to send tweet")
        return False

image_queue = ImageQueue()
recent_ids = deque([], 25)

def log_tweepy_err(e: tweepy.TweepError, prefix: str=""):
    # Tweepy's TweepError exception class is weird,
    # that's why I have this set up
    if prefix != "":
        errmsg = prefix + ": "

    if e.api_code:
        code = e.api_code
        msg = e.args[0][0]["message"]
        errmsg += "{0} (error code {1})".format(msg, code)
    else:
        errmsg += str(e)
    logger.error(errmsg)

def parse_config():
    global config_dict
    with open(CONFIG_FILE) as f:
        config_dict = json.load(f)
    verify_keys()

def verify_keys():
    # TODO: clean up this function

    def do_assert(condition, err_msg: str):
        assert condition, err_msg

    def verify_blacklist_keys():
        blacklist = config_dict["blacklist"]
        for k in ("tags", "artists"):
            do_assert(k in blacklist,
            "Required key \"%s\" not found in blacklist config" % k)
            do_assert(isinstance(blacklist[k], list), "Required blacklist key "
                "\"%s\" must have value of type array (list)" % k)

    def verify_twitter_keys():
        twkeys = config_dict["twitter_keys"]
        for k in ("consumer", "consumer_secret", "access", "access_secret"):
            do_assert(k in twkeys,
                "Required key \"%s\" not found in Twitter keys config" %k)
            do_assert(isinstance(twkeys[k], str) and twkeys[k] != "",
                "Required key \"%s\" must have value of type string "
                "and can't be blank" % k)

    for k in ("tags", "blacklist", "twitter_keys", "score", "favorites"):
        do_assert(k in config_dict,
            "Required key \"%s\" not found in config" % k)

        if k in ("blacklist", "twitter_keys"):
            do_assert(isinstance(config_dict[k], dict), "Required key "
                "%s must have value of type object (dict)" % k)

        elif k == "tags":
            do_assert(isinstance(config_dict[k], list), "Required key "
                "\"%s\" must have value of type array (list)" % k)
            do_assert(len(config_dict[k]) < 3,
                "Search queries are limited to 2 tags")
            do_assert(len(config_dict[k]) > 0, "Tags cannot be blank")

        elif k in ("score", "favorites"):
            do_assert(isinstance(config_dict[k], int), "Required key "
                "\"%s\" must have value of integer" % k)

        else:
            do_assert(isinstance(config_dict[k], str), "Required key "
                "\"%s\" must have value of type string and can't be blank" % k)

    verify_twitter_keys()
    verify_blacklist_keys()

def get_danbooru_request(endpoint: str, params: dict):
    # Convert params dict to URI string
    if params:
        params_list = []
        params_str = "?"
        for k in params:
            if not (isinstance(k, str) and isinstance(params[k], str)):
                continue
            params_list.append("{0}={1}".format(k, params[k]))
        params_str += "&".join(params_list)
    else:
        params_str = ""

    global db_request_raw
    r = requests.get(DB_API_URL.format(endpoint=endpoint, params=params_str))
    db_request_raw = r.content.decode()
    return r.json()

def populate_queue(limit: int=50, attempts=1):
    # Step 1: Assemble URI parameters
    tags_str = "+".join(config_dict["tags"])
    logger.info("Building post queue for tag(s) \"%s\"", tags_str)
    params = {
        "tags":tags_str,
        "limit":str(limit),
        "random":"true"
    }

    # Step 2: Get request and check if it returned any posts
    posts = get_danbooru_request("posts", params)
    assert posts, "Provided tag(s) \"%s\" returned no posts" % tags_str

    # Step 3: Iterate through and filter posts
    # Unfiltered posts are added to image queue
    postcount = 0
    for post in posts:
        # Evaluate post data for filtering
        if not eval_post(post):
            continue

        # Enqueue post info
        postid = post["id"]
        # Use "large_file_url" just in case post's actual image is too big
        url = post["large_file_url"]
        source = get_source(post)
        image_queue.enqueue(postid, DB_URL + url, source)
        logger.debug("Added post ID %s to queue", postid)
        postcount += 1

    # Step 4: Log queue size when done, otherwise run function again
    if postcount > 0:
        logger.info("%s/%s images added to queue, current queue size is now %s",
            postcount, len(posts), len(image_queue))
        return

    # Give up after 3 attempts
    if attempts >= 3:
        raise SystemExit
    logger.info("No matching images added to queue, retrying in 5s")
    attempts += 1
    time.sleep(5)
    populate_queue(limit, attempts)

def eval_post(post: dict):
    # Returns False if given post is caught by any filters below
    postid = post["id"]

    # Check if post is banned (no image available)
    if post["is_banned"]:
        logger.debug("Post ID %s is banned and skipped", postid)
        return False

    # Check if rating is q(uestionable) or e(xplicit)
    if post["rating"] != "s":
        logger.debug("Post ID %s skipped due to rating (rated %s)", postid,
            post["rating"])
        return False

    # Evaluate tags, score, favorite count, and filetype
    return (eval_tags(post["tag_string"], postid) and
        eval_score(post["score"], postid) and
        eval_favorites(post["fav_count"], postid) and
        eval_filetype(post["large_file_url"], postid)
    )

def eval_tags(tag_string: str, postid):
    # Return True if no tags are in blacklist, otherwise return False
    tags = tag_string.split()
    blacklist_config = config_dict["blacklist"]

    for t in tags:
        if t in TAG_BLACKLIST or t in blacklist_config["tags"]:
            logger.debug("Post ID %s contains blacklisted tag: %s", postid, t)
            return False
        if t in USER_BLACKLIST or t in blacklist_config["artists"]:
            logger.debug("Post ID %s is by blacklisted artist: %s", postid, t)
            return False
    return True

def eval_score(score: int, postid):
    # Return True if post's score meets threshold, otherwise return False
    if score >= config_dict["score"]:
        return True
    logger.debug("Post ID %s did not meet score threshold of %s", postid,
        config_dict["score"])
    return False

def eval_favorites(count: int, postid):
    # Same as eval_score, but evaluate based on post's favorite count
    if count >= config_dict["favorites"]:
        return True
    logger.debug("Post ID %s did not meet favorite count threshold of %s",
        postid, config_dict["score"])
    return False

def eval_filetype(filename: str, postid):
    filetype = filename.split(".")[-1]
    if filetype.lower() in ("jpg", "jpeg", "png", "gif"):
        return True
    logger.debug("Post ID %s has invalid filetype of .%s", postid, filetype)
    return False

def get_source(post: dict):
    def get_da_permalink(url: str):
        info = url.split("_by_")[-1].split(".")[0]
        info_dash_split = info.split("-")
        if len(info_dash_split) < 2:
            return url
        artist, art_id = info_dash_split
        return DA_URL.format(artist=artist, id=art_id)

    if "bad_id" in post["tag_string_general"]:
        logger.debug("Post ID %s contains tag \"bad_id\"", post["id"])
        return

    if post["pixiv_id"]:
        return PIXIV_URL.format(id=post["pixiv_id"])

    source = post["source"]
    if source.startswith("https://twitter.com/"):
        return "@" + source.split("/")[3]
    if "deviantart.net/" in source:
        return get_da_permalink(source)

    for domain in SOURCE_DOMAINS:
        if domain + "/" in source:
            return source
    return

def dump_db_request(error):
    # Dumps response content to file when bot runs into an error
    # while building queue
    if type(error) in (SystemExit, KeyboardInterrupt, AssertionError):
        return
    with open(DB_DUMP_FILE, "w", encoding="utf_8") as f:
        f.write(db_request_raw)
        logger.info("Error occurred while populating queue, "
            "response content dumped to %s", DB_DUMP_FILE)

def post_image(bot: TweetPicBot):
    # Step 1: Repopulate queue if size is less than 5
    if len(image_queue) < 5:
        try:
            populate_queue()
        except Exception as e:
            dump_db_request(e)
            raise

    # Step 2: Check if post ID was already posted in the last 25 tweets
    postdata = image_queue.get_first_item()
    postid = postdata[0]
    while postid in recent_ids:
        # Discard post in queue
        image_queue.dequeue()
        logger.debug("Post ID %s was uploaded in the last 25 tweets", postid)
        postdata = image_queue.get_first_item()
        postid = postdata[0]

    # Step 3: Download image to file
    url = postdata[1]
    try:
        file_path = download_file(postid, url)
    except TypeError as type_error:
        # If received content type is not in ALLOWED_CONTENT_TYPES list above,
        # then move on to next post in queue
        logger.error("%s, moving on to next post in queue", type_error)

        image_queue.dequeue()
        # Add 1s delay to make sure we're not flooding Danbooru with requests
        time.sleep(1)
        post_image(bot)
        return
    except:
        logger.exception("Failed to download image for post ID %s, "
            "will retry at next scheduled interval", postid)
        return

    # Step 4: Prepare tweet content
    if postid == TRISH_ID:
        source_str = "Trish-chan (aka @PlayerOneTimmy as a girl)\n"
    else:
        source_str = ""

    source = postdata[2]
    if source:
        source_str += "Source: %s" % source

    # Step 5: Send tweet and add post ID to recent IDs list
    if bot.send_tweet(file_path, source_str):
        logger.info("Tweet sent successfully! "
                "Post ID of uploaded image was %s", postid)

        # Discard post from queue when done
        image_queue.dequeue()
        logger.debug("%s post(s) remaining in queue", len(image_queue))

        # Save recent IDs file
        recent_ids.append(postid)
        save_recent_ids()

    else:
        logger.info(
            "Tweet for post ID %s will be sent at next scheduled interval",
            postid)

def download_file(postid: str, url: str):
    # based from http://stackoverflow.com/a/16696317
    local_filename = "{0}.{1}".format(postid, url.split('.')[-1])
    path = "{0}/{1}".format(IMG_DIR, local_filename)

    if local_filename in os.listdir(IMG_DIR + "/"):
        logger.debug("Image already exists: %s", path)
        return path

    logger.info("Downloading post ID %s to %s", postid, path)
    time_start = time.time()

    r = requests.get(url, stream=True)
    # Check Content-Type header in case Danbooru returns HTML/XML file
    # instead of an image for any reason
    if "Content-Type" in r.headers:
        # Strip out extra stuff in content headers for some images
        # (example: "image/jpeg; charset=utf-8")
        content_type = r.headers["Content-Type"].split("; ")[0]
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise TypeError("Content type '%s' is invalid for media upload"
                % content_type)

    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk: # filter out keep-alive new chunks
                f.write(chunk)
    time_end = time.time()

    elapsed = round(time_end - time_start, 3)
    logger.info("Completed downloading %s in %ss", local_filename, elapsed)
    return path

def logging_setup():
    logging.basicConfig(format=LOG_FMT, level=logging.INFO)
    logging.Formatter.converter = time.gmtime

    filehandler = logging.FileHandler("events.log")
    fmt = logging.Formatter("[%(asctime)s] " + LOG_FMT, "%Y-%m-%dT%H:%M:%SZ")
    filehandler.setFormatter(fmt)
    logging.getLogger().addHandler(filehandler)

    logging.getLogger("oauthlib").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)
    logging.getLogger("schedule").setLevel(logging.WARNING)
    logging.getLogger("tweepy").setLevel(logging.WARNING)

def load_recent_ids():
    if not RECENT_IDS_FILE in os.listdir():
        logger.debug("%s not found in current directory, skipping",
            RECENT_IDS_FILE)
        return

    with open(RECENT_IDS_FILE) as f:
        id_count = 0
        for line in f:
            line = line.strip("\n")
            if line.isdigit():
                recent_ids.append(line)
                id_count += 1
        logger.debug("Found %s post ID(s) in file", id_count)
        logger.info("Recent post IDs loaded")

def save_recent_ids():
    with open(RECENT_IDS_FILE, mode="w") as f:
        f.write("\n".join(recent_ids))
        logger.debug("Saved last 25 post IDs to %s", RECENT_IDS_FILE)

def main_loop(interval: int=30):
    # Check interval range
    assert 60 > interval > 0, "Interval must be between 1 and 59 minutes"

    # Make images directory if it doesn't exist
    if not IMG_DIR in os.listdir():
        logger.info("Creating images directory")
        os.mkdir(IMG_DIR)

    # Set up Twitter API client
    bot = TweetPicBot(config_dict["twitter_keys"])

    # Build initial queue, then set up schedule
    try:
        # Post immediately if current UTC minute is divisible by interval
        current_min = time.gmtime().tm_min
        if current_min % interval == 0:
            post_image(bot)
        else:
            populate_queue()
    except Exception as e:
        dump_db_request(e)
        raise
    for m in range(0, 60, interval):
        schedule.every().hour.at("00:%s" % m).do(post_image, bot)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    logging_setup()
    logger.info("Timmy's Danbooru Twitter Bot v%s is starting up",
        __version__)

    try:
        load_recent_ids()
        parse_config()
        main_loop()
    except (KeyboardInterrupt, SystemExit):
        # Use Ctrl-C to terminate the bot
        logger.info("Now shutting down")
    except AssertionError as e:
        logger.error(e)
    except:
        logger.exception("Exception occurred, now shutting down")

    schedule.clear()
