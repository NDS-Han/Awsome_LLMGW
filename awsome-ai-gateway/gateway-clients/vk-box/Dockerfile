# Copyright 2026 © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms.
#
# vk-box — gateway-cli(api_key_helper) 만 담은 격리 컨테이너.
# gw.sh vk 를 호스트에 gateway-cli 를 설치하지 않고도 Docker 로 실행할 수 있게 한다.
FROM public.ecr.aws/docker/library/python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 상위 디렉터리(awsome-ai-gateway)를 build context 로 사용하기 때문에
# gateway-cli 디렉터리 전체를 COPY 한 뒤 pip install 한다.
COPY gateway-cli/pyproject.toml ./
COPY gateway-cli/src ./src

RUN pip install --no-cache-dir . awscli

# OIDC token cache / AWS SSO cache 저장용
RUN useradd -m -u 1000 appuser
USER appuser
WORKDIR /home/appuser
ENV HOME=/home/appuser

ENTRYPOINT ["api-key-helper"]
