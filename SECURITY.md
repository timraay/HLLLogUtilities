# Data protection with HLLLogUtilities

HLLLogUtilities (or **HLU** in short) is a log capturing utility for Hell Let Loose. In order to get the information it needs, it utilizes RCON. Thus it requires your RCON credentials in order to operate.

Of course, you need to be careful with whom you grant RCON access. And as someone who will be a stranger to most of you, I think it is more than reasonable to clarify how exactly HLU will handle your private information, and what options you get to keep your password more safe.

## Public or private

I am providing a public instance of the bot. You can invite it right to your Discord server without having to worry about hosting or fees (but feel free to [buy me a coffee](https://ko-fi.com/abusify)). This means however that I, a third party, will need to be indirectly given access to your RCON. Whether you trust me with that information is up to you. If you don't, you can always host the bot yourself (see "Open source" below).

## Storing passwords

The bot does not store your information without consent. You can choose whether the bot should save your password or not. By saving it, it is written to a database. That way you can quickly reselect the server later on, and can HLU reconnect your session in case the bot was restarted. If you decline, the credentials are kept in memory until the log capture session is over (or the bot is stopped).

Credentials you use are tied to the Discord server you're in. Once submitted, passwords are no longer visible to anyone using the bot. By default, only Administrators are able to run commands.

## Open source

HLU is open source software. That means that the code behind the software is visible to anyone, and can also be contributed to. Anyone is able to explore what the tool is doing, and verify that it is indeed legit.

With the software being open source, you can download a copy of the code and run it yourself. That way you don't have to share your credentials with a third party. This also allows you to tweak certain settings as per the [config file](https://github.com/timraay/HLLLogUtilities/blob/main/config.ini).

## Can you trust me?

There's always things that can go wrong. For that reason I can never guarantee 100% safety, even though I'll try my best. But in the end, I assume no liability for the unintentional or malicious breach of data. For any questions you can always reach me on Discord (`@Abu#6969`). If you appreciate my work, consider [donating on Ko-fi]((https://ko-fi.com/abusify)). Thanks!
