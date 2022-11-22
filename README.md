# HLLLogUtilities ![GitHub release (latest by date)](https://img.shields.io/github/v/release/timraay/HLLLogUtilities)

<img align="right" width="250" height="250" src="icon.png">

> For any issues or feature requests, please [open an Issue](https://github.com/timraay/HLLLogUtilities/issues) here on GitHub.

HLLLogUtilities (or HLU in short) is a Discord bot providing a clean interface to record and download logs in different formats from your Hell Let Loose server. It is capable of providing highly detailed logs with information no other program is able to capture.

You can [invite HLU to your server](https://discord.com/oauth2/authorize?client_id=1033779011005980773&scope=bot+applications.commands&permissions=35840) right away with no costs whatsoever, or [host a private instance](#setup-guide) yourself!

## Easy to use!

It takes only a few clicks to create a capture session and start recording logs. Just give a start and end time and select the server you want to record! From there on you can download the logs in formats such as `txt`, `csv` and `json`.

## Super-detailed logs!

HLU makes great use of its asynchronous backend by opening up multiple connections, that way it can poll player information it a blazing-fast rate. It is capable of computing all sorts of events no other tool has been capable of so far, such as players changing roles, players redeploying, players joining, leaving or creating units, and more!

# Planned features

This is a non-exhaustive list in no particular order of everything I *may* add one day, whenever I feel like it.

- [ ] Exporting a single match from a session
- [ ] Exporting statistics from a session or match
- [ ] Replace the info model core for more precise logs
- [ ] Uploading and converting existing logs
- [ ] Add timezone settings
- [ ] Command localization

# Quickstart

### Prerequisites
- A Discord server you have Administrator permissions in
- A Hell Let Loose server you know the RCON credentials of

### Guide

To get started with HLLLogUtilities, follow the below steps!

1. [Invite HLLLogUtilities](https://discord.com/oauth2/authorize?client_id=1033779011005980773&scope=bot+applications.commands&permissions=35840) to your Discord server.
2. Type in `/`, and select the `/session new` command.
3. Fill in the parameters.
    - Give it a name that you can later identify the session by, for instance "First-time test".
    - Give it a start and end time. The times have to be in UTC, and make sure they're not relative. So "14:30" is fine, but not "in 30 minutes". You can also use "now".
    - For the server, select "Custom". You likely won't have any other options there yet anyway.
4. Run the command. Confirm that the presented information is correct and press "Confirm". Otherwise dismiss the message and run the command again.
5. It'll ask you for your RCON credentials. Open the form and fill them in. 
    - The name doesn't have to be your actual server's name. It's purely so you will later know what server the bot is talking about.
6. Choose whether you want to save the credentials or not.

Your session is now scheduled! Now, let's wait for it to gather some logs and then view them.

1. Type in `/`, and select the `/session logs` command.
2. Fill in the parameters.
    - Select the session you created earlier.
    - The format you can leave on `text` for now.
3. Run the command.

And that's everything! You can see all of your sessions with the `/session list` command. Just note that they'll be deleted after 14 days. To manage your server credentials, use the `/credentials` command.

> **NOTE:** All commands require **Administrator permissions**. You can add exceptions for specific roles, channels and/or users under *Server Settings > Integrations > HLL Log Utilities*.

# Setup Guide

## Prerequisites
- A machine to host on, such as a VPS, dedicated server or your own PC
- [Git](https://git-scm.com/downloads)
- (optional) [Python](https://www.python.org/downloads) 3.7 or above, only required when running from source
- (optional) [Docker](https://docs.docker.com/get-docker/), only required when running with docker
- (optional) [SQLite3](https://www.sqlite.org/download.html), only required when running with docker

## Guide

### Discord setup

The bot integrates using Discord slash/application commands, which requires a discord application created in Discord's developer portal:

1. Go to the [Discord developer portal](https://discord.com/developers/applications) and create a new application.
2. Go to the "Bot" tab and add a bot.
3. (optional) Add a profile picture
4. (optional) Disable the "Public Bot" setting
5. Click on the "Reset Token" button and copy your token.
6. The bot token will be put into the `config.ini` file later. Make sure there's no trailing spaces.

### Cloning the code

To host your own instance of HLU, there's a few steps you have to follow. Let's start off by cloning the code from GitHub. For this you need to have Git installed.

1. Open a command terminal in the parent directory you want the files to be saaved. In here, we will later create a directory containing all the files.
2. Run the following command to download the files from GitHub:
```shell
git clone https://github.com/timraay/HLLLogUtilities.git
```
3. Go into the directory we just made:
```shell
cd HLLLogUtilities
```

### Hosting from source

1. Install all needed Python libraries.
```shell
pip install -r requirements.txt
```

> **NOTE:** Windows users may get an error saying they need to install Visual C++ 2014. To do this, follow the below steps:
> 1. Download and run [Visual Studio Build Tools](https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022)
> 2. Under "Workloads", select "Desktop development with C++"
> 3. Under "Invidivual components", select most relevant versions of both "C++ x64/x86 build tools" and "Windows SDK"
> 4. Install everything

5. Put the discord bot token into the `config.ini` file.

And that's everything! Now we just need to run it.

6. Start the bot!
```shell
python bot.py
```

Note that the bot will shut down whenever you close this terminal.

### Hosting using docker

You can run HLU in a docker container to simplify the setup.

1. You need create an empty database file, first, you need `sqlite3` installed for that:
```shell
sqlite3 sessions.db "VACUUM;"
```
2. Start the container:
```shell
docker-compose up -d
```

The container will run in the background, to stop the bot run:
```shell
docker-compose down
```

<div align=center>
    
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/abusify)

</div>
