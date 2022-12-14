#!/bin/sh

cd /opt/map-trackinator

while true
do

  python map-trackinator.py &
  CHILD_PID=$!
  
  GDIFF_LINES=0
  while [ "$GDIFF_LINES" -lt 1 ]
  do
    sleep 30
    git fetch
    GDIFF_LINES=$(git diff origin/master | wc -l)
    echo "GDIFF_LINES=$GDIFF_LINES"
  done
  
  git pull

  kill $CHILD_PID
  sleep 2
  kill -9 $CHILD_PID

  wait $CHILD_PID

done

