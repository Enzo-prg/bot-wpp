#!/bin/bash
gunicorn -w 4 -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker app:app
