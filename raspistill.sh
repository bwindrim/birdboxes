#!/bin/bash

FILE=$(date +"BB1_%FT%H-%M-%S.jpg")

/usr/bin/raspistill -awb off -awbg '1.0,1.0' -n -t 500 -w 640 -h 480 -q 75 -o - | tee /mnt/capture/$FILE

