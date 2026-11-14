> ## Documentation Index
> Fetch the complete documentation index at: https://docs.openserv.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Build a Fullstack Agentic App

> From zero to a working fullstack agentic app.

[YouTube video player](https://www.youtube.com/embed/8Xe_BWxwdak?si=ycmlPUp6tS4brFxc)

Watch: Build a Fullstack Agentic App.

## Build a Fullstack Agentic App

### 1. Start from the project template

Use the official OpenServ project template:

* Project template: [Fullstack Agentic App](https://platform.openserv.ai/project-templates?preview=216)

Create the workspace from this template, then:

1. Go to **Secrets** and set the secret for the frontend URL (where your app should receive callbacks).
2. Assign that secret to the REST API agent so it knows where to send responses.

### 2. Run the frontend

Clone the demo app:

* GitHub: [demoapp-openserv](https://github.com/issa-me-sush/demoapp-openserv)

This app:

* Provides a chat interface for sending requests.
* Calls the REST API agent with your prompt + parameters.
* Waits for the callback from the agent and renders the result.

Point the app to your backend by:

* Updating the environment variable or config to use your ngrok or production URL (including the `/api/callback` route or similar expected endpoint).
* Keeping the secret in OpenServ updated with the latest URL.

Once wired, you can move from local ngrok URLs to a stable production domain without changing your agent logic.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.