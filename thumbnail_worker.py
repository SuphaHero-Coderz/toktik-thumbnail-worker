import os
import logging
import json
import uuid
import redis
import boto3
import botocore
from moviepy.editor import VideoFileClip

LOG = logging
# Credentials and Queue for listening
REDIS_QUEUE_LOCATION = os.getenv('REDIS_QUEUE', 'localhost')
QUEUE_NAME = 'queue:thumbnail'

INSTANCE_NAME = uuid.uuid4().hex

LOG.basicConfig(
    level=LOG.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

s3 = boto3.client('s3', 
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY"),
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY"),
)

# listen to queue and fetch work when arrive
def watch_queue(redis_conn, queue_name, callback_func, timeout=30):
    active = True

    while active:
        # Fetch a json-encoded task using a blocking (left) pop
        packed = redis_conn.blpop([queue_name], timeout=timeout)

        if not packed:
            # if nothing is returned, poll a again
            continue

        _, packed_task = packed

        # If it's treated to a poison pill, quit the loop
        if packed_task == b'DIE':
            active = False
        else:
            task = None
            try:
                task = json.loads(packed_task)
            except Exception:
                LOG.exception('json.loads failed')
                data = { "status" : "-1", "message" : "An error occurred" }
                redis_conn.publish("thumbnail", json.dumps(data))
            if task:
                callback_func(task["object_key"])
                data = { "status" : "1", "message" : "Successfully generated thumbnails" }
                redis_conn.publish("thumbnail", json.dumps(data))

def download_video(object_key: str):
    try:
        LOG.info("Downloading file from S3 for thumbnail generation")
        s3.download_file(os.getenv("BUCKET_NAME"), f"{object_key}/encoded.mp4", "encoded.mp4")
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            LOG.error("ERROR: file was not found on S3")
        else:
            LOG.error("ERROR: file download")
            raise

def upload_thumbnail(object_key: str):
    LOG.info("Uploading converted video")
    try:
        s3.upload_file(f"./thumbnail.jpg", os.getenv("BUCKET_NAME"), f"{object_key}/thumbnail.jpg")    
        LOG.info("Successfully uploaded converted video")
    except botocore.exceptions.ClientError as e:
        LOG.error(e)

def generate_thumbnail(object_key: str):
    clip = VideoFileClip("encoded.mp4")
    time = clip.duration / 5
    clip_name = clip.filename.split('.')[0]
    clip.save_frame("thumbnail.jpg", t=time)

def cleanup():
    try:
        os.remove("./encoded.mp4")
        os.remove("./thumbnail.jpg")
        LOG.info("All files deleted successfully.")
    except OSError:
        LOG.error("Error occurred while deleting files.")

# thumbnail creation logic, capture a fram according to time and save if as a jpg
def execute_thumbnail(object_key: str):
    download_video(object_key)
    generate_thumbnail(object_key)
    upload_thumbnail(object_key)
    cleanup()


def main():
    LOG.info('Starting a worker...')
    LOG.info('Unique name: %s', INSTANCE_NAME)
    host, *port_info = REDIS_QUEUE_LOCATION.split(':')
    port = tuple()
    if port_info:
        port, *_ = port_info
        port = (int(port),)

    named_logging = LOG.getLogger(name=INSTANCE_NAME)
    named_logging.info('Trying to connect to %s [%s]', host, REDIS_QUEUE_LOCATION)
    redis_conn = redis.Redis(host=host, *port)
    watch_queue(
        redis_conn,
        QUEUE_NAME,
        execute_thumbnail)


if __name__ == '__main__':
    main()
