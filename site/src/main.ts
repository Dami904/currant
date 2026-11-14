import { startChrome } from "./chrome";
import { startDemo } from "./demo";
import { startHero } from "./hero";

startHero(); // first, so its scroll handler sets the stage's tone before the header reads it
startChrome();
startDemo();
