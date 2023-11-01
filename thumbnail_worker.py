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

THUMBNAIL_NAME = "thumbnail.jpg"
ENCODED_FILENAME = "encoded.mp4"

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
    """
    Listens to queue `queue_name` and passes messages to `callback_func`
    """
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
    """
    Downloads the encoded mp4 file from S3.
    """
    try:
        LOG.info("Downloading file from S3 for thumbnail generation")
        s3.download_file(os.getenv("BUCKET_NAME"), f"{object_key}/{ENCODED_FILENAME}", f"{ENCODED_FILENAME}")
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            LOG.error("ERROR: file was not found on S3")
        else:
            LOG.error("ERROR: file download")
            raise

def upload_thumbnail(object_key: str):
    """
    Uploads the generated thumbnail back to S3.
    """
    LOG.info("Uploading converted video")
    try:
        s3.upload_file(f"./{THUMBNAIL_NAME}", os.getenv("BUCKET_NAME"), f"{object_key}/{THUMBNAIL_NAME}")    
        LOG.info("Successfully uploaded converted video")
    except botocore.exceptions.ClientError as e:
        LOG.error(e)

def generate_thumbnail(object_key: str):
    """
    Generates a thumbnail by capturing a frame at a fifth of the video's duration.
    """
    clip = VideoFileClip(ENCODED_FILENAME)
    time = clip.duration / 5
    clip_name = clip.filename.split('.')[0]
    clip.save_frame(THUMBNAIL_NAME, t=time)

def cleanup():
    """
    Deletes files involved in the thumbnail creation -- encoded video and thumbnail itself -- after uploading.
    """
    def delete_file(filepath: str):
        try:
            os.remove(filepath)
            LOG.info(f"Successfully deleted file: {filepath}")
        except OSError:
            LOG.error(f"Error occurred while deleting file: {filepath}")

    delete_file(f"./{THUMBNAIL_NAME}")
    delete_file(f"./{ENCODED_FILENAME}")

def execute_thumbnail(object_key: str):
    """
    Main process for thumbnail generation.
    """
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
