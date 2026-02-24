FROM python:3.12-bookworm

WORKDIR /app

ADD cmdb /app/cmdb
COPY requirements.txt /app

RUN pip install -r requirements.txt

ADD etc/cmdb.conf etc/cmdb.conf

EXPOSE 80

CMD ["python3", "-m",  "cmdb", "-s", "--local"]
