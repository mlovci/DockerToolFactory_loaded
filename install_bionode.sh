#!/bin/bash

cd /
wget http://nodejs.org/dist/v0.10.31/node-v0.10.31-linux-x64.tar.gz
tar xzvf node-v0.10.31-linux-x64.tar.gz
cd node-v0.10.31-linux-x64
export NODEPATH=`pwd`/bin
echo "export PATH=$NODEPATH:\$PATH" >> ~/.bash_profile
export PATH=$NODEPATH:$PATH
git clone https://github.com/bionode/bionode-ncbi.git
cd bionode-ncbi
#git checkout fork/dld
npm install -g
cd ..
npm install -g bionode-sra


#helper script to download using bionode
cd /
git clone https://gist.github.com/2adc03cc50c4cf3220fe.git dlSRA/
cd /usr/bin
ln -s /dlSRA/gistfile1.txt download_sra.sh
chmod a+x /usr/bin/download_sra.sh

