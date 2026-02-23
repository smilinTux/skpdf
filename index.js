/**
 * @smilintux/skpdf
 *
 * SKPDF - PDF field extraction and auto-fill.
 * JS/TS bridge to the Python skpdf package.
 * Install: pip install skpdf
 */

const { execSync } = require("child_process");

const VERSION = "0.1.0";
const PYTHON_PACKAGE = "skpdf";

function checkInstalled() {
  for (const py of ["python3", "python"]) {
    try {
      execSync(`${py} -c "import skpdf"`, { stdio: "pipe" });
      return true;
    } catch {}
  }
  return false;
}

function run(args) {
  return execSync(`skpdf ${args}`, { encoding: "utf-8" });
}

module.exports = { VERSION, PYTHON_PACKAGE, checkInstalled, run };
