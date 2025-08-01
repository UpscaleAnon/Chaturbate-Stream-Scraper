# Chaturbate Stream Scraper
<img width="842" height="599" alt="image" src="https://github.com/user-attachments/assets/74372a60-fea5-4d32-9771-88b36c821cbe" />


This tool can automatically scrape chaturbate streams to grab the .ts stream files.

Originally I used OBS to record streams, which is painful and stupid on so many levels, plus is limited to 1 stream at any given time. So I got this script made with ChatGPT and it works wonders and figured I'd share.

From my testing, it has been able to scrape 40 streams at the same time, but I would not be surprised if they timed you out or something, though it hasn't happened to me yet, despite having downloaded 500GB over a single night.

Features persistent list so restarting the GUI doesn't wipe everything. If it fails to download a segment file, it keep retrying for 30 seconds and then assumes stream has either restarted or ended, in which case it'll re-pull the URL and try 5 times before giving up.

There is an "Infinite" option if you do wich to constantly keep track of a stream, which makes it retry forever. You can choose which streams this applies to.

Due to a streamer's sometimes unstable internet, some segments are somewhat corrupted, notably near the start or end of a stream. My concat setup (which I'll provide later) can scan for these, but including them doesn't cause any issues, it'll just appear glitchy at those segments.

Chaturbate stream URLs often end with a /? in the URL, the script handles that just fine.

The script will store files local to the script in a folder called "Downloads", then a subfolder based on username, then subfolder based on time and date of your PC.

If a stream restarts for some reason, it'll check the time again and make a new folder, to avoid overwriting existing files, since every time a stream starts, the segments are named 000001.ts and goes up.

Alternatively, I have a RAM version of the script that downloads .ts files directly to RAM and outputs it into an MKV file, without re-encoding.

It also has options to scan, segments for corruption, but that requires having a temporary directory so the segments get put on a drive for a split second before merging into the MKV. Though one could set up a RAM disk and have it use that as a temp path.

Checking for corruption isn't technically necessary, but it might provide some useful information.

With the RAM version of the script, if you plan to end a stream capture, don't just quit the GUI, unless you don't care about the information files. To properly save them, stop the downloads, wait for them to stop fully then close the GUI.

The RAM script will occasionally write small MKV files that consist of broken segments only if a streamer has connection issues. If you want, you could probably use Everything by VoidTools, check for any .mkv file below 5MB or something and mass delete them.

I will also have a Telegram channel where I occasionally post streams: https://t.me/ChaturbateScraper


# Requirements
Script has only been tested on Windows 10 with Python 3.10

pip install requests pyperclip (Or run the included .bat script)

Ffmpeg installed to PATH (If using RAM version of the script or my concatenating script)


# FAQ
Q: Video quality?

A: There is no re-encode happening or recording, it's downloading the original stream files, so the quality is as high as it gets, without any filesize inflation.

But feel free to re-encode yourself if you want to.

Q: How do I merge the videos?

A: Either use the RAM version of the script that outputs an MKV directly, or wait until I publish the concatenating script for the individual .ts files.

Q: How do I get around 429 errors or other rate limits?

A: Package the script as 2 EXEs with different name then use a VPN with split tunneling to have one run through VPN and other through main IP.
Though generally this is only really an issue if you go crazy and download 50+ streams at the same time. I'm not sure on exact limit, but I've encountered it at close to 60 streams.

Q: My CPU can't take scraping as many streams as you

A: Either live with it, or disable the corruption check. My Ryzen 9 9950X3D gets hammered when I download close to 60 streams due to the corruption checker.

Q: I'm getting retry timeouts a lot

A: Don't set retry interval to anything higher than 5. It'll spend too long to check for a segment, causing it to time out. Maybe try lowering it if you're experiencing retry timeouts or increase retry timeout from 30 seconds to 60.


# TODO
1: Improve TempSegment folder by having subfolder dedicated to each streamer to avoid potential issues (Ready for next version)

2: Build EXE or make a script to build EXE, or both

3: Add a remove button to rightclick context menu (Ready for next version)

4: Add optional filesize limit to split videos (Ready I think? Need to test)

5: Allow for input of username instead of demanding full URL (Ready for next version)

6: Customizeable doubleclick setting in GUI that can be set to either quick retry, open folder, start, stop, toggle infinite or remove. (Ready for next version)

7: Quicksettings in the GUI for retry timer, retry amount, retry timeout, infinite retry pause timer, filesize limit and corruption check which stores those values in a config.txt (Ready for next version)
