docker stop grok2api_python
docker rm grok2api_python
docker build -t mygrok .
docker run -it -d --name grok2api_python -p 4444:3000 -v $(pwd)/data:/data --env-file .env mygrok