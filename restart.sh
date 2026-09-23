#!/bin/bash
sudo pkill -f controller.py
sudo pkill -f rangers_monitor.py
sudo pkill -f yankees_monitor.py
sudo pkill -f giants_monitor.py
sleep 2
sudo python3 -u /home/coledallen/projects/goal_horn/controller.py >> /home/coledallen/projects/goal_horn/controller.log 2>&1 &
python3 -u /home/coledallen/projects/goal_horn/rangers_monitor.py >> /home/coledallen/projects/goal_horn/rangers_monitor.log 2>&1 &
python3 -u /home/coledallen/projects/goal_horn/yankees_monitor.py >> /home/coledallen/projects/goal_horn/yankees_monitor.log 2>&1 &
python3 -u /home/coledallen/projects/goal_horn/giants_monitor.py >> /home/coledallen/projects/goal_horn/giants_monitor.log 2>&1 &
python3 -u /home/coledallen/projects/goal_horn/panthers_monitor.py >> /home/coledallen/projects/goal_horn/panthers_monitor.log 2>&1 &
echo "All scripts restarted."
