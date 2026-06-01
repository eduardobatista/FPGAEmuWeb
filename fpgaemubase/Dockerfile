# syntax=docker/dockerfile:1
# FROM python:3.10
# FROM python:3.10-slim-bookworm
FROM debian:bookworm-slim

ADD ./builtghdl6.tar.gz /usr/local
ADD ./surferdist.tar.gz /home/surferdist

WORKDIR /home

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends gcc libc6-dev libgnat-12 make zlib1g-dev libllvm14 && \
    apt-get autoremove -y && \
    apt-get clean 
