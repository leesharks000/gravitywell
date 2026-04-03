#!/bin/bash
set -e
echo "Gravity Well — Deploy Helper"
echo ""

if [ ! -d .git ]; then
    echo "Initializing git..."
    git init
    git add .
    git commit -m "Gravity Well v0.3.0"
fi

echo "Next steps:"
echo ""
echo "1. Create repo: https://github.com/new (name: gravitywell)"
echo "2. Push:"
echo "   git remote add origin https://github.com/YOUR_USERNAME/gravitywell.git"
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""
echo "3. Deploy: https://dashboard.render.com/blueprints"
echo "   Connect repo → auto-deploys from render.yaml"
echo ""
echo "4. Set env vars in Render dashboard:"
echo "   - ZENODO_TOKEN"
echo "   - ADMIN_TOKEN"
echo ""
echo "5. Test: curl https://gravitywell.onrender.com/v1/health"
