> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Build a Custom Agent

> A guided build with video and steps.

[YouTube video player](https://www.youtube.com/embed/sHCFRgzKDKg?si=x7TfmZD4MLrpzQ6r)

Watch: Build a custom agent.

## Build a Custom Agent

### Starter repository

To get going fast, clone the Hyperliquid demo agent:

* GitHub: [basic-agent](https://github.com/issa-me-sush/basic-agent)

The repo is structured around the OpenServ TypeScript SDK:

* `capabilities/`
  * `test.ts`: basic “hello world” style capability you can use to verify that the agent server is wired correctly.
  * `trade.ts`: more advanced Hyperliquid trading capability (documented in more detail under the Hyperliquid Agent example).
* `agent-server.ts`: boots the server and registers capabilities in a modular way.

### Environment variables

Create a `.env` file with:

```bash theme={null}
# Required
OPENSERV_API_KEY=your_openserv_api_key_here

# Optional
PORT=7380
HYPERLIQUID_TESTNET=false  # set to 'true' for testnet
```

* `OPENSERV_API_KEY` is created from the **Your Agents → Create Secret Key** action after registering the agent via **Add Agent**.
* `PORT` is optional (defaults to 7380).
* `HYPERLIQUID_TESTNET` controls whether the agent talks to mainnet or testnet.

Once the agent server is running, you can expose it via ngrok or a production domain, register it in **Add Agent**, and then call its capabilities in natural language from workflows or other agents.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.