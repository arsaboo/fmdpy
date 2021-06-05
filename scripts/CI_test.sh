# make and install
set -e
echo "Building...."
./scripts/build_pip.sh
echo "(Done)"

echo "Installing..."
python -m  pip install ./dist/fmdpy-*.whl
echo "(Done)"

# test
echo "1:10" | fmdpy "new songs" \
        && [ "$(find -name '*.mp3' | wc -l)" -eq 10 ]

echo "1 2 3 4" | fmdpy "new songs" opus \
        && [ "$(find -name '*.opus' | wc -l)" -eq 4 ]


# cleaning
echo "Cleaning..."
rm -rf ./dist
echo "(Done)"

# uninstall
echo "Uninstalling..."
python -m pip uninstall -y fmdpy
echo "(Done)"
