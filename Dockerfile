FROM python:3.8-alpine

WORKDIR /code
COPY upstream/requirements.txt .
RUN pip install -r requirements.txt
COPY ./upstream/ .

ENTRYPOINT [ "python", "/code/bot.py" ]
