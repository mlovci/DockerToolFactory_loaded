# Toolfactory image
#
# VERSION       0.1
# This Dockerfile is the base system for executing scripts by the DockerToolFactory.
FROM debian:jessie
#original ... MAINTAINER Marius van den Beek, m.vandenbeek@gmail.com
MAINTAINER Michael T Lovci michaeltlovci@gmail.com
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
RUN easy_install pip
RUN pip install --upgrade numpy pysam tornado matplotlib pip pandas ipython rpy2 
RUN pip install scikit-learn 
RUN pip install cython 
RUN pip install setuptools 
RUN Rscript -e 'source("http://bioconductor.org/biocLite.R"); biocLite(c("DESeq", "DESeq2", "edgeR", "EDASeq"))'
RUN Rscript -e 'install.packages(c("latticeExtra", "ggplot2", "reshape", "gridExtra"), dependencies=TRUE, repos="http://cran.us.r-project.org")'
RUN apt-get install bc
RUN easy_install intermine
RUN git clone https://github.com/YeoLab/clipper.git
RUN pip install HTSeq pybedtools
RUN cd clipper && git checkout clip_analysis_fixes && easy_install .
RUN git clone https://github.com/YeoLab/flotilla.git && cd flotilla && pip install .
RUN git clone https://github.com/YeoLab/gscripts.git && cd gscripts && easy_install .
RUN git clone https://github.com/samtools/htslib && cd htslib && autoconf && ./configure && make && make install
#RUN git clone git://github.com/samtools/samtools.git  && cd samtools && make && make install
#add galaxy user (could be any username).
#1001 will be replaced by the actual user id of the system user
#executing the galaxy tool, so that file write operations are possible.
RUN wget http://hgdownload.cse.ucsc.edu/admin/exe/linux.x86_64/blat/blat -O /usr/bin/blat && chmod a+x /usr/bin/blat
RUN wget http://weblogo.berkeley.edu/release/weblogo.2.8.2.tar.gz -O weblogo.2.8.2.tar.gz && tar zxvf weblogo.2.8.2.tar.gz && cp weblogo/seqlogo /usr/bin/.
RUN wget http://homer.salk.edu/homer/configureHomer.pl -O configureHomer.pl && perl configureHomer.pl -install homer
RUN adduser galaxy -u 451
RUN pip install --upgrade git+https://github.com/matplotlib/matplotlib.git
RUN apt-get update
RUN apt-get install -y emacs
RUN apt-get install -y emboss emboss-lib
#RUN wget ftp://emboss.open-bio.org/pub/EMBOSS/EMBOSS-6.6.0.tar.gz && tar xzvf EMBOSS-6.6.0.tar.gz && cd EMBOSS-6.6.0 && ./configure --without-x &&  make && make install
RUN apt-get install -y mysql-client
RUN pip install bx-python gffutils biopython
ADD install_bionode.sh /install_bionode.sh
RUN bash /install_bionode.sh
ENV PATH /weblogo:$PATH
RUN usermod -aG staff galaxy
#VOLUME ["/home/galaxy/"]
RUN mkdir /home/galaxy/job_working_directory
WORKDIR /home/galaxy/job_working_directory
USER galaxy
#ENTRYPOINT chown -R galaxy /home/galaxy/ && su - galaxy
CMD /bin/bash
