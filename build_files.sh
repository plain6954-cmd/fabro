#!/bin/bash
# Build script for Vercel deployment
echo "Installing project dependencies..."
python3 -m pip install -r requirements.txt

echo "Collecting static assets..."
python3 manage.py collectstatic --noinput --clear

echo "Vercel build complete."
