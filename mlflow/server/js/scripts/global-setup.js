const { execSync } = require('child_process');
const os = require('os');

// How do I set a timezone in my Jest config?
// https://stackoverflow.com/a/56482581/6943581

module.exports = () => {
  // Take from: https://github.com/capaj/set-tz/blob/master/index.js
  if (os.platform() === 'win32') {
    const previousTZ = execSync('tzutil /g').toString();
    const cleanup = () => {
      execSync(`tzutil /s "${previousTZ}"`);
      console.log(`timezone was restored to ${previousTZ}`);
    };
    execSync(`tzutil /s "GMT Standard Time"`);
    console.warn(`timezone changed, if process is killed, run manually: tzutil /s "${previousTZ}"`);
    process.on('exit', cleanup);
    process.on('SIGINT', function() {
      process.exit(2);
    });
  } else {
    process.env.TZ = 'GMT';
  }
};
