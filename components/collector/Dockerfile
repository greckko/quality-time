FROM python:3.9.0-buster

LABEL maintainer="Frank Niessink <frank.niessink@ictu.nl>"
LABEL description="Quality-time collector"

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

RUN useradd --create-home collector
WORKDIR /home/collector
USER collector

COPY src /home/collector

HEALTHCHECK CMD python -c "from datetime import datetime as dt, timedelta; import sys; sys.exit(dt.now() - dt.fromisoformat(open('/tmp/health_check.txt').read().strip()) > timedelta(seconds=600))"

CMD ["python", "/home/collector/quality_time_collector.py"]
