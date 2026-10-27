import { createApp } from "./server.js";
import { settingsFromEnv } from "./settings.js";

const endpoint = new URL("http://" + (process.env.AWS_LAMBDA_HTTP_ENDPOINT || "127.0.0.1:3000"));
if (!endpoint.hostname || !endpoint.port) throw new Error("AWS_LAMBDA_HTTP_ENDPOINT must be host:port.");
const server = createApp(settingsFromEnv());
server.listen(Number(endpoint.port), endpoint.hostname);
process.on("SIGTERM", () => server.close(() => process.exit(0)));
