# 更新代码需要重建容器
# 运行此脚本前请确保已安装 Docker
# 使用方法：在项目根目录下运行 ./rebuild.sh
docker stop grok2api_python
docker rm grok2api_python
docker build -t mygrok .
docker run -it -d --name grok2api_python -p 4444:3000 -v $(pwd)/data:/data --env-file .env mygrok