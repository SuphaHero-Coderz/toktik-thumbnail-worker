# Build upon this image "alpine" is a lightweight distro
FROM python:3.11-slim

# Install all the requirements
COPY requirements.txt /app/requirements.txt

# Install all the requirements
RUN pip install -r /app/requirements.txt

# Copy everthing from . to /app inside the 'box'
COPY thumbnail_worker.py /app
COPY .env /app
WORKDIR /app

# How to run it when we start up the box?
CMD ["python", "./thumbnail_worker.py"]
