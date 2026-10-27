import { createStudioApp } from "./server.js";
import { settingsFromEnv } from "./config.js";

const endpoint = new URL("http://" + (process.env.AWS_LAMBDA_HTTP_ENDPOINT || "127.0.0.1:3001"));
const server = createStudioApp(settingsFromEnv());
server.listen(Number(endpoint.port), endpoint.hostname);
process.on("SIGTERM", () => server.close(() => process.exit(0)));
