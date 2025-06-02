from flask_socketio import SocketIO
from flask_pymongo import PyMongo
from apscheduler.schedulers.background import BackgroundScheduler
import logging

# Initialize extensions
mongo = PyMongo()
scheduler = BackgroundScheduler()
logger = logging.getLogger(__name__)
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')