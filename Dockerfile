# Toolfactory image
#
# VERSION       0.1
# This Dockerfile is the base system for executing scripts by the DockerToolFactory.

FROM debian:jessie

MAINTAINER Marius van den Beek, m.vandenbeek@gmail.com

# make sure the package repository is up to date
ENV DEBIAN_FRONTEND noninteractive
RUN apt-get -qq update

# Install all requirements that are recommend by the Galaxy project
RUN apt-get install --no-install-recommends -y autoconf automake build-essential gfortran \
cmake git-core libatlas-base-dev libblas-dev liblapack-dev mercurial subversion python-dev \
pkg-config openjdk-7-jre python-setuptools adduser zlib1g-dev ghostscript r-base-core \
 graphicsmagick-imagemagick-compat

RUN apt-get install -y python-virtualenv libfreetype6-dev exonerate bedtools wget curl \
libcurl4-openssl-dev libssl-dev libreadline-dev libxml2-dev samtools liblzma-dev \
libpcre3-dev libbz2-dev

RUN easy_install numpy pysam tornado matplotlib pycurl pip pandas ipython rpy2

RUN Rscript -e 'source("http://bioconductor.org/biocLite.R"); biocLite("DESeq", "DESeq2", "edgeR", "EDASeq")'
RUN Rscript -e 'install.packages(c("latticeExtra", "ggplot2", "reshape", "gridExtra"), dependencies=TRUE, repos="http://cran.us.r-project.org")'

#add galaxy user (could be any username).
#1001 will be replaced by the actual user id of the system user
#executing the galaxy tool, so that file write operations are possible.
RUN adduser galaxy -u 1001

#VOLUME ["/home/galaxy/"]
RUN mkdir /home/galaxy/job_working_directory
WORKDIR /home/galaxy/job_working_directory
USER galaxy


#ENTRYPOINT chown -R galaxy /home/galaxy/ && su - galaxy
CMD /bin/bash
