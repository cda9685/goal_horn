Start a cron job:
`sudo crontab -e`

Add the following to the bottom of the file:
`@reboot python3 -u /path/to/goal_horn/rangers_goal_horn.py >> /path/to/goal_horn/goal_horn.log 2>&1`

This will start the script in the background on boot and write its status to a log.

Set up a log rotation:
`sudo vim /etc/logrotate.d/goal_horn`

Add the following:
<pre>
  /path/to/goal_horn/goal_horn.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
</pre>
