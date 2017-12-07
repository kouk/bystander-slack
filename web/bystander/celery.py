from celery import Celery

from .conf import REDIS_HOST


app = Celery('tasks', broker="redis://{}:6379/0".format(REDIS_HOST))
app.autodiscover_tasks(lambda: ['bystander'])
