#!/bin/bash

while true; do
    echo "$(date +'%Y-%m-%d %H:%M:%S') - This is stderr message" >&2
    sleep 1
done