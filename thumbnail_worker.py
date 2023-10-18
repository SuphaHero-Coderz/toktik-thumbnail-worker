import os
import logging
import json
import uuid
import redis
from moviepy.editor import VideoFileClip

LOG = logging
REDIS_QUEUE_LOCATION = os.getenv('REDIS_QUEUE', 'localhost')
QUEUE_NAME = 'queue:thumbnail'

INSTANCE_NAME = uuid.uuid4().hex

LOG.basicConfig(
    level=LOG.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


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
                redis_conn.publish("thumbnail", "failed")
            if task:
                callback_func(task["name"])
                redis_conn.publish("thumbnail", "ok")


def execute_thumbnail(file_path: str):
    clip = VideoFileClip(file_path)
    time = VideoFileClip(file_path).duration / 5
    clip_name = clip.filename.split('.')[0]
    clip.save_frame(f"{clip_name}.jpg", t=time)


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
