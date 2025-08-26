rm -rf ../flash
mkdir -p ../flash/apps/badgemon_source
rsync -avs ../badgemon-source/ ../flash/apps/badgemon_source
cd ../flash/apps/badgemon_source
rm -rf .git* .vscode/ design/ docs/ TODO.md LICENCE *.code-workspace *.gitignore README.md .env *.gitmodules flash.sh __pycache__
find . -name '*.ase' | xargs rm
find . -name '__pycache__' | xargs rm -rf
cd ../../
mpremote a0 cp --recursive apps :
cd ../badgemon-source
rm -rf ../flash
mpremote a0 reset
