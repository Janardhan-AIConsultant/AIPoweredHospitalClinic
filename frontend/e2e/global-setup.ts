import { backendEnv, prepareDatabase } from "./support";

export default function globalSetup() {
  prepareDatabase(backendEnv());
}
