FROM python:3.13-alpine

RUN apk add --no-cache sqlite sqlite-dev

WORKDIR /code
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY ./ .

RUN sqlite3 /code/sessions.db "VACUUM;"

ENTRYPOINT [ "python", "/code/bot.py" ]
