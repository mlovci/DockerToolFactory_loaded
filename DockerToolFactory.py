# DockerToolFactory.py
# see https://bitbucket.org/mvdbeek/DockerToolFactory

import sys 
import shutil 
import subprocess 
import os 
import time 
import tempfile 
import argparse
import tarfile
import re
import shutil
import math
import fileinput
from os.path import abspath 

progname = os.path.split(sys.argv[0])[1] 
myversion = 'V001.1 March 2014' 
verbose = False 
debug = False
toolFactoryURL = 'https://bitbucket.org/fubar/galaxytoolfactory'

# if we do html we need these dependencies specified in a tool_dependencies.xml file and referred to in the generated
# tool xml
toolhtmldepskel = """<?xml version="1.0"?>
<tool_dependency>
    <package name="ghostscript" version="9.10">
        <repository name="package_ghostscript_9_10" owner="devteam" prior_installation_required="True" />
    </package>
    <package name="graphicsmagick" version="1.3.18">
        <repository name="package_graphicsmagick_1_3" owner="iuc" prior_installation_required="True" />
    </package>
        <readme>
           %s
       </readme>
</tool_dependency>
"""

protorequirements = """<requirements>
      <requirement type="package" version="9.10">ghostscript</requirement>
      <requirement type="package" version="1.3.18">graphicsmagick</requirement>
      <container type="docker">toolfactory/custombuild:%s</container>
</requirements>"""

def timenow():
    """return current time as a string
    """
    return time.strftime('%d/%m/%Y %H:%M:%S', time.localtime(time.time()))

html_escape_table = {
     "&": "&amp;",
     ">": "&gt;",
     "<": "&lt;",
     "$": "\$"
     }

def html_escape(text):
     """Produce entities within text."""
     return "".join(html_escape_table.get(c,c) for c in text)

def cmd_exists(cmd):
     return subprocess.call("type " + cmd, shell=True, 
           stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0

def edit_dockerfile(dockerfile):
    '''we have to change the userid of galaxy inside the container to the id with which the tool is run,
       otherwise we have a mismatch in the file permissions inside the container'''
    uid=os.getuid()
    for line in fileinput.FileInput(dockerfile, inplace=1):
        sys.stdout.write(re.sub("RUN adduser galaxy.*",  "RUN adduser galaxy -u {0}\n".format(uid), line))

def build_docker(dockerfile, docker_client, image_tag='base'):
    '''Given the path to a dockerfile, and a docker_client, build the image, if it does not
    exist yet.'''
    image_id='toolfactory/custombuild:'+image_tag
    existing_images=", ".join(["".join(d['RepoTags']) for d in docker_client.images()])
    if image_id in existing_images:
        print 'docker container exists, skipping build'
        return image_id
    print "Building Docker image, using Dockerfile:{0}".format(dockerfile)
    build_process=docker_client.build(fileobj=open(dockerfile, 'r'), tag=image_id)
    print "succesfully dispatched docker build process, building now"
    build_log=[line for line in build_process] #will block until image is built.
    return image_id 

def construct_bind(host_path, container_path=False, binds=None, ro=True):
    #TODO remove container_path if it's alwyas going to be the same as host_path
    '''build or extend binds dictionary with container path. binds is used
    to mount all files using the docker-py client.'''
    if not binds:
        binds={}
    if isinstance(host_path, list):
        for k,v in enumerate(host_path):
            if not container_path:
                container_path=host_path[k]
            binds[host_path[k]]={'bind':container_path, 'ro':ro}
            container_path=False #could be more elegant
        return binds
    else:
        if not container_path:
            container_path=host_path
        binds[host_path]={'bind':container_path, 'ro':ro}
        return binds

def switch_to_docker(opts):
    import docker #need local import, as container does not have docker-py
    docker_client=docker.Client()
    toolfactory_path=abspath(sys.argv[0])
    dockerfile=os.path.dirname(toolfactory_path)+'/Dockerfile'
    edit_dockerfile(dockerfile)
    image_id=build_docker(dockerfile, docker_client)
    binds=construct_bind(host_path=opts.script_path, ro=False)
    binds=construct_bind(binds=binds, host_path=abspath(opts.output_dir), ro=False)
    if len(opts.input_tab)>0:
        binds=construct_bind(binds=binds, host_path=opts.input_tab, ro=True)
    if not opts.output_tab == 'None':
        binds=construct_bind(binds=binds, host_path=opts.output_tab, ro=False)
    if opts.make_HTML:
        binds=construct_bind(binds=binds, host_path=opts.output_html, ro=False)
    if opts.make_Tool:
        binds=construct_bind(binds=binds, host_path=opts.new_tool, ro=False)
        binds=construct_bind(binds=binds, host_path=opts.help_text, ro=True)
    binds=construct_bind(binds=binds, host_path=toolfactory_path)
    volumes=binds.keys()
    sys.argv=[abspath(opts.output_dir) if sys.argv[i-1]=='--output_dir' else arg for i,arg in enumerate(sys.argv)] ##inject absolute path of working_dir
    cmd=['python', '-u']+sys.argv+['--dockerized', '1']
    container=docker_client.create_container(
        image=image_id,
        user='galaxy',
        volumes=volumes,
        command=cmd
        )
    docker_client.start(container=container[u'Id'], binds=binds)
    docker_client.wait(container=container[u'Id'])
    logs=docker_client.logs(container=container[u'Id'])
    print "".join([log for log in logs])

class ScriptRunner:
    """class is a wrapper for an arbitrary script
    """

    def __init__(self,opts=None,treatbashSpecial=True, image_tag='base'):
        """
        cleanup inputs, setup some outputs
        
        """
        self.opts = opts
        self.useGM = cmd_exists('gm')
        self.useIM = cmd_exists('convert')
        self.useGS = cmd_exists('gs')
        self.temp_warned = False # we want only one warning if $TMP not set
        self.treatbashSpecial = treatbashSpecial
        self.image_tag = image_tag
        os.chdir(abspath(opts.output_dir))
        self.thumbformat = 'png'
        self.toolname_sanitized = re.sub('[^a-zA-Z0-9_]+', '_', opts.tool_name) # a sanitizer now does this but..
        self.toolname = opts.tool_name
        self.toolid = self.toolname
        self.myname = sys.argv[0] # get our name because we write ourselves out as a tool later
        self.pyfile = self.myname # crude but efficient - the cruft won't hurt much
        self.xmlfile = '%s.xml' % self.toolname_sanitized
        s = open(self.opts.script_path,'r').readlines()
        s = [x.rstrip() for x in s] # remove pesky dos line endings if needed
        self.script = '\n'.join(s)
        fhandle,self.sfile = tempfile.mkstemp(prefix=self.toolname_sanitized,suffix=".%s" % (opts.interpreter))
        tscript = open(self.sfile,'w') # use self.sfile as script source for Popen
        tscript.write(self.script)
        tscript.close()
        self.indentedScript = '\n'.join([' %s' % html_escape(x) for x in s]) # for restructured text in help
        self.escapedScript = '\n'.join([html_escape(x) for x in s])
        self.elog = os.path.join(self.opts.output_dir,"%s_error.log" % self.toolname_sanitized)
        if opts.output_dir: # may not want these complexities
            self.tlog = os.path.join(self.opts.output_dir,"%s_runner.log" % self.toolname_sanitized)
            art = '%s.%s' % (self.toolname_sanitized,opts.interpreter)
            artpath = os.path.join(self.opts.output_dir,art) # need full path
            artifact = open(artpath,'w') # use self.sfile as script source for Popen
            artifact.write(self.script)
            artifact.close()
        self.cl = []
        self.html = []
        a = self.cl.append
        a(opts.interpreter)
        if self.treatbashSpecial and opts.interpreter in ['bash','sh']:
            a(self.sfile)
        else:
            a('-') # stdin
	for input in opts.input_tab:
	  a(input) 
        if opts.output_tab == 'None': #If tool generates only HTML, set output name to toolname
            a(str(self.toolname_sanitized)+'.out')
        a(opts.output_tab)
	for param in opts.additional_parameters:
          param, value=param.split(',')
          a('--'+param)
          a(value)
        #print self.cl
        self.outFormats = opts.output_format
        self.inputFormats = [formats for formats in opts.input_formats]
        self.test1Input = '%s_test1_input.xls' % self.toolname_sanitized
        self.test1Output = '%s_test1_output.xls' % self.toolname_sanitized
        self.test1HTML = '%s_test1_output.html' % self.toolname_sanitized

    def makeXML(self):
        """
        Create a Galaxy xml tool wrapper for the new script as a string to write out
        fixme - use templating or something less fugly than this example of what we produce

        <tool id="reverse" name="reverse" version="0.01">
            <description>a tabular file</description>
            <command interpreter="python">
            reverse.py --script_path "$runMe" --interpreter "python" 
            --tool_name "reverse" --input_tab "$input1" --output_tab "$tab_file" 
            </command>
            <inputs>
            <param name="input1"  type="data" format="tabular" label="Select a suitable input file from your history"/>

            </inputs>
            <outputs>
            <data format=opts.output_format name="tab_file"/>

            </outputs>
            <help>
            
**What it Does**

Reverse the columns in a tabular file

            </help>
            <configfiles>
            <configfile name="runMe">
            
# reverse order of columns in a tabular file
import sys
inp = sys.argv[1]
outp = sys.argv[2]
i = open(inp,'r')
o = open(outp,'w')
for row in i:
     rs = row.rstrip().split('\t')
     rs.reverse()
     o.write('\t'.join(rs))
     o.write('\n')
i.close()
o.close()
 

            </configfile>
            </configfiles>
            </tool>
        
        """ 
        newXML="""<tool id="%(toolid)s" name="%(toolname)s" version="%(tool_version)s">
%(tooldesc)s
%(requirements)s
<command interpreter="python">
%(command)s
</command>
<inputs>
%(inputs)s
</inputs>
<outputs>
%(outputs)s
</outputs>
<configfiles>
<configfile name="runMe">
%(script)s
</configfile>
</configfiles>

%(tooltests)s

<help>

%(help)s

</help>
</tool>""" # needs a dict with toolname, toolname_sanitized, toolid, interpreter, scriptname, command, inputs as a multi line string ready to write, outputs ditto, help ditto

        newCommand="""
        %(toolname_sanitized)s.py --script_path "$runMe" --interpreter "%(interpreter)s" 
            --tool_name "%(toolname)s" %(command_inputs)s %(command_outputs)s """
        # may NOT be an input or htmlout - appended later
        tooltestsTabOnly = """
        <tests>
        <test>
        <param name="input1" value="%(test1Input)s" ftype="tabular"/>
        <param name="runMe" value="$runMe"/>
        <output name="tab_file" file="%(test1Output)s" ftype="tabular"/>
        </test>
        </tests>
        """
        tooltestsHTMLOnly = """
        <tests>
        <test>
        <param name="input1" value="%(test1Input)s" ftype="tabular"/>
        <param name="runMe" value="$runMe"/>
        <output name="html_file" file="%(test1HTML)s" ftype="html" lines_diff="5"/>
        </test>
        </tests>
        """
        tooltestsBoth = """<tests>
        <test>
        <param name="input1" value="%(test1Input)s" ftype="tabular"/>
        <param name="runMe" value="$runMe"/>
        <output name="tab_file" file="%(test1Output)s" ftype="tabular" />
        <output name="html_file" file="%(test1HTML)s" ftype="html" lines_diff="10"/>
        </test>
        </tests>
        """
        xdict = {}
        #xdict['requirements'] = '' 
        #if self.opts.make_HTML:
        xdict['requirements'] = protorequirements % self.image_tag
        xdict['tool_version'] = self.opts.tool_version
        xdict['test1Input'] = self.test1Input
        xdict['test1HTML'] = self.test1HTML
        xdict['test1Output'] = self.test1Output   
        if self.opts.make_HTML and self.opts.output_tab <> 'None':
            xdict['tooltests'] = tooltestsBoth % xdict
        elif self.opts.make_HTML:
            xdict['tooltests'] = tooltestsHTMLOnly % xdict
        else:
            xdict['tooltests'] = tooltestsTabOnly % xdict
        xdict['script'] = self.escapedScript 
        # configfile is least painful way to embed script to avoid external dependencies
        # but requires escaping of <, > and $ to avoid Mako parsing
        if self.opts.help_text:
            helptext = open(self.opts.help_text,'r').readlines()
            helptext = [html_escape(x) for x in helptext] # must html escape here too - thanks to Marius van den Beek
            xdict['help'] = ''.join([x for x in helptext])
        else:
            xdict['help'] = 'Please ask the tool author (%s) for help as none was supplied at tool generation\n' % (self.opts.user_email)
        coda = ['**Script**','Pressing execute will run the following code over your input file and generate some outputs in your history::']
        coda.append('\n')
        coda.append(self.indentedScript)
        coda.append('\n**Attribution**\nThis Galaxy tool was created by %s at %s\nusing the Galaxy Tool Factory.\n' % (self.opts.user_email,timenow()))
        coda.append('See %s for details of that project' % (toolFactoryURL))
        coda.append('Please cite: Creating re-usable tools from scripts: The Galaxy Tool Factory. Ross Lazarus; Antony Kaspi; Mark Ziemann; The Galaxy Team. ')
        coda.append('Bioinformatics 2012; doi: 10.1093/bioinformatics/bts573\n')
        xdict['help'] = '%s\n%s' % (xdict['help'],'\n'.join(coda))
        if self.opts.tool_desc:
            xdict['tooldesc'] = '<description>%s</description>' % self.opts.tool_desc
        else:
            xdict['tooldesc'] = ''
        xdict['command_outputs'] = '' 
        xdict['outputs'] = '' 
        if self.opts.input_tab <> 'None':
            xdict['command_inputs'] = '--input_tab'
            xdict['inputs']=''
            for i,input in enumerate(self.inputFormats):
                xdict['inputs' ]+='<param name="input{0}"  type="data" format="{1}" label="Select a suitable input file from your history"/> \n'.format(i+1, input)
                xdict['command_inputs'] += ' $input{0}'.format(i+1)
        else:
            xdict['command_inputs'] = '' # assume no input - eg a random data generator       
            xdict['inputs'] = ''
        # I find setting the job name not very logical. can be changed in workflows anyway. xdict['inputs'] += '<param name="job_name" type="text" label="Supply a name for the outputs to remind you what they contain" value="%s"/> \n' % self.toolname
        xdict['toolname'] = self.toolname
        xdict['toolname_sanitized'] = self.toolname_sanitized
        xdict['toolid'] = self.toolid
        xdict['interpreter'] = self.opts.interpreter
        xdict['scriptname'] = self.sfile
        if self.opts.make_HTML:
            xdict['command_outputs'] += ' --output_dir "$html_file.files_path" --output_html "$html_file" --make_HTML "yes"'
            xdict['outputs'] +=  ' <data format="html" name="html_file"/>\n'
        else:
            xdict['command_outputs'] += ' --output_dir "./"' 
        #print self.opts.output_tab
        if self.opts.output_tab!="None":
            xdict['command_outputs'] += ' --output_tab "$tab_file"'
            xdict['outputs'] += ' <data format="%s" name="tab_file"/>\n' % self.outFormats
        xdict['command'] = newCommand % xdict
        #print xdict['outputs']
        xmls = newXML % xdict
        xf = open(self.xmlfile,'w')
        xf.write(xmls)
        xf.write('\n')
        xf.close()
        # ready for the tarball


    def makeTooltar(self):
        """
        a tool is a gz tarball with eg
        /toolname_sanitized/tool.xml /toolname_sanitized/tool.py /toolname_sanitized/test-data/test1_in.foo ...
        """
        retval = self.run()
        if retval:
            print >> sys.stderr,'## Run failed. Cannot build yet. Please fix and retry'
            sys.exit(1)
        tdir = self.toolname_sanitized
        os.mkdir(tdir)
        self.makeXML()
        if self.opts.make_HTML:
            if self.opts.help_text:
                hlp = open(self.opts.help_text,'r').read()
            else:
                hlp = 'Please ask the tool author for help as none was supplied at tool generation\n'
            if self.opts.include_dependencies:
                tooldepcontent = toolhtmldepskel  % hlp
                depf = open(os.path.join(tdir,'tool_dependencies.xml'),'w')
                depf.write(tooldepcontent)
                depf.write('\n')
                depf.close()
        if self.opts.input_tab <> 'None': # no reproducible test otherwise? TODO: maybe..
            testdir = os.path.join(tdir,'test-data')
            os.mkdir(testdir) # make tests directory
	    for i in self.opts.input_tab:
		  #print i
	          shutil.copyfile(i,os.path.join(testdir,self.test1Input))
            if not self.opts.output_tab:
                shutil.copyfile(self.opts.output_tab,os.path.join(testdir,self.test1Output))
            if self.opts.make_HTML:
                shutil.copyfile(self.opts.output_html,os.path.join(testdir,self.test1HTML))
            if self.opts.output_dir:
                shutil.copyfile(self.tlog,os.path.join(testdir,'test1_out.log'))
        outpif = '%s.py' % self.toolname_sanitized # new name
        outpiname = os.path.join(tdir,outpif) # path for the tool tarball
        pyin = os.path.basename(self.pyfile) # our name - we rewrite ourselves (TM)
        notes = ['# %s - a self annotated version of %s generated by running %s\n' % (outpiname,pyin,pyin),]
        notes.append('# to make a new Galaxy tool called %s\n' % self.toolname)
        notes.append('# User %s at %s\n' % (self.opts.user_email,timenow()))
        pi=[line.replace('if opts.dockerized==0:', 'if False:') for line in open(self.pyfile)] #do not run docker in the generated tool
        notes += pi
        outpi = open(outpiname,'w')
        outpi.write(''.join(notes))
        outpi.write('\n')
        outpi.close()
        stname = os.path.join(tdir,self.sfile)
        if not os.path.exists(stname):
            shutil.copyfile(self.sfile, stname)
        xtname = os.path.join(tdir,self.xmlfile)
        if not os.path.exists(xtname):
            shutil.copyfile(self.xmlfile,xtname)
        tarpath = "%s.gz" % self.toolname_sanitized
        tar = tarfile.open(tarpath, "w:gz")
        tar.add(tdir,arcname=self.toolname_sanitized)
        tar.close()
        shutil.copyfile(tarpath,self.opts.new_tool)
        shutil.rmtree(tdir)
        ## TODO: replace with optional direct upload to local toolshed?
        return retval


    def compressPDF(self,inpdf=None,thumbformat='png'):
        """need absolute path to pdf
           note that GS gets confoozled if no $TMP or $TEMP
           so we set it
        """
        assert os.path.isfile(inpdf), "## Input %s supplied to %s compressPDF not found" % (inpdf,self.myName)
        hlog = os.path.join(self.opts.output_dir,"compress_%s.txt" % os.path.basename(inpdf))
        sto = open(hlog,'a')
        our_env = os.environ.copy()
        our_tmp = our_env.get('TMP',None)
        if not our_tmp:
            our_tmp = our_env.get('TEMP',None)
        if not (our_tmp and os.path.exists(our_tmp)):
            newtmp = os.path.join(self.opts.output_dir,'tmp')
            try:
                os.mkdir(newtmp)
            except:
                sto.write('## WARNING - cannot make %s - it may exist or permissions need fixing\n' % newtmp)
            our_env['TEMP'] = newtmp
            if not self.temp_warned:
               sto.write('## WARNING - no $TMP or $TEMP!!! Please fix - using %s temporarily\n' % newtmp)
               self.temp_warned = True          
        outpdf = '%s_compressed' % inpdf
        cl = ["gs", "-sDEVICE=pdfwrite", "-dNOPAUSE", "-dUseCIEColor", "-dBATCH","-dPDFSETTINGS=/printer", "-sOutputFile=%s" % outpdf,inpdf]
        x = subprocess.Popen(cl,stdout=sto,stderr=sto,cwd=self.opts.output_dir,env=our_env)
        retval1 = x.wait()
        sto.close()
        if retval1 == 0:
            os.unlink(inpdf)
            shutil.move(outpdf,inpdf)
            os.unlink(hlog)
        hlog = os.path.join(self.opts.output_dir,"thumbnail_%s.txt" % os.path.basename(inpdf))
        sto = open(hlog,'w')
        outpng = '%s.%s' % (os.path.splitext(inpdf)[0],thumbformat)
        if self.useGM:        
            cl2 = ['gm', 'convert', inpdf, outpng]
        else: # assume imagemagick
            cl2 = ['convert', inpdf, outpng]
        x = subprocess.Popen(cl2,stdout=sto,stderr=sto,cwd=self.opts.output_dir,env=our_env)
        retval2 = x.wait()
        sto.close()
        if retval2 == 0:
             os.unlink(hlog)
        retval = retval1 or retval2
        return retval


    def getfSize(self,fpath,outpath):
        """
        format a nice file size string
        """
        size = ''
        fp = os.path.join(outpath,fpath)
        if os.path.isfile(fp):
            size = '0 B'
            n = float(os.path.getsize(fp))
            if n > 2**20:
                size = '%1.1f MB' % (n/2**20)
            elif n > 2**10:
                size = '%1.1f KB' % (n/2**10)
            elif n > 0:
                size = '%d B' % (int(n))
        return size

    def makeHtml(self):
        """ Create an HTML file content to list all the artifacts found in the output_dir
        """

        galhtmlprefix = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd"> 
        <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en"> 
        <head> <meta http-equiv="Content-Type" content="text/html; charset=utf-8" /> 
        <meta name="generator" content="Galaxy %s tool output - see http://g2.trac.bx.psu.edu/" /> 
        <title></title> 
        <link rel="stylesheet" href="/static/style/base.css" type="text/css" /> 
        </head> 
        <body> 
        <div class="toolFormBody"> 
        """ 
        galhtmlattr = """<hr/><div class="infomessage">This tool (%s) was generated by the <a href="https://bitbucket.org/fubar/galaxytoolfactory/overview">Galaxy Tool Factory</a></div><br/>""" 
        galhtmlpostfix = """</div></body></html>\n"""

        flist = os.listdir(self.opts.output_dir)
        flist = [x for x in flist if x <> 'Rplots.pdf']
        flist.sort()
        html = []
        html.append(galhtmlprefix % progname)
        html.append('<div class="infomessage">Galaxy Tool "%s" run at %s</div><br/>' % (self.toolname,timenow()))
        fhtml = []
        if len(flist) > 0:
            logfiles = [x for x in flist if x.lower().endswith('.log')] # log file names determine sections
            logfiles.sort()
            logfiles = [x for x in logfiles if abspath(x) <> abspath(self.tlog)]
            logfiles.append(abspath(self.tlog)) # make it the last one
            pdflist = []
            npdf = len([x for x in flist if os.path.splitext(x)[-1].lower() == '.pdf'])
            for rownum,fname in enumerate(flist):
                dname,e = os.path.splitext(fname)
                sfsize = self.getfSize(fname,self.opts.output_dir)
                if e.lower() == '.pdf' : # compress and make a thumbnail
                    thumb = '%s.%s' % (dname,self.thumbformat)
                    pdff = os.path.join(self.opts.output_dir,fname)
                    retval = self.compressPDF(inpdf=pdff,thumbformat=self.thumbformat)
                    if retval == 0:
                        pdflist.append((fname,thumb))
                    else:
                        pdflist.append((fname,fname))
                if (rownum+1) % 2 == 0:
                    fhtml.append('<tr class="odd_row"><td><a href="%s">%s</a></td><td>%s</td></tr>' % (fname,fname,sfsize))
                else:
                    fhtml.append('<tr><td><a href="%s">%s</a></td><td>%s</td></tr>' % (fname,fname,sfsize))
            for logfname in logfiles: # expect at least tlog - if more
                if abspath(logfname) == abspath(self.tlog): # handled later
                    sectionname = 'All tool run'
                    if (len(logfiles) > 1):
                        sectionname = 'Other'
                    ourpdfs = pdflist
                else:
                    realname = os.path.basename(logfname)
                    sectionname = os.path.splitext(realname)[0].split('_')[0] # break in case _ added to log
                    ourpdfs = [x for x in pdflist if os.path.basename(x[0]).split('_')[0] == sectionname]
                    pdflist = [x for x in pdflist if os.path.basename(x[0]).split('_')[0] <> sectionname] # remove
                nacross = 1
                npdf = len(ourpdfs)

                if npdf > 0:
                    nacross = math.sqrt(npdf) ## int(round(math.log(npdf,2)))
                    if int(nacross)**2 != npdf:
                        nacross += 1
                    nacross = int(nacross)
                    width = min(400,int(1200/nacross))
                    html.append('<div class="toolFormTitle">%s images and outputs</div>' % sectionname)
                    html.append('(Click on a thumbnail image to download the corresponding original PDF image)<br/>')
                    ntogo = nacross # counter for table row padding with empty cells
                    html.append('<div><table class="simple" cellpadding="2" cellspacing="2">\n<tr>')
                    for i,paths in enumerate(ourpdfs): 
                        fname,thumb = paths
                        s= """<td><a href="%s"><img src="%s" title="Click to download a PDF of %s" hspace="5" width="%d" 
                           alt="Image called %s"/></a></td>\n""" % (fname,thumb,fname,width,fname)
                        if ((i+1) % nacross == 0):
                            s += '</tr>\n'
                            ntogo = 0
                            if i < (npdf - 1): # more to come
                               s += '<tr>'
                               ntogo = nacross
                        else:
                            ntogo -= 1
                        html.append(s)
                    if html[-1].strip().endswith('</tr>'):
                        html.append('</table></div>\n')
                    else:
                        if ntogo > 0: # pad
                           html.append('<td>&nbsp;</td>'*ntogo)
                        html.append('</tr></table></div>\n')
                logt = open(logfname,'r').readlines()
                logtext = [x for x in logt if x.strip() > '']
                html.append('<div class="toolFormTitle">%s log output</div>' % sectionname)
                if len(logtext) > 1:
                    html.append('\n<pre>\n')
                    html += logtext
                    html.append('\n</pre>\n')
                else:
                    html.append('%s is empty<br/>' % logfname)
        if len(fhtml) > 0:
           fhtml.insert(0,'<div><table class="colored" cellpadding="3" cellspacing="3"><tr><th>Output File Name (click to view)</th><th>Size</th></tr>\n')
           fhtml.append('</table></div><br/>')
           html.append('<div class="toolFormTitle">All output files available for downloading</div>\n')
           html += fhtml # add all non-pdf files to the end of the display
        else:
            html.append('<div class="warningmessagelarge">### Error - %s returned no files - please confirm that parameters are sane</div>' % self.opts.interpreter)
        html.append(galhtmlpostfix)
        htmlf = file(self.opts.output_html,'w')
        htmlf.write('\n'.join(html))
        htmlf.write('\n')
        htmlf.close()
        self.html = html


    def run(self):
        """
        scripts must be small enough not to fill the pipe!
        """
        if self.treatbashSpecial and self.opts.interpreter in ['bash','sh']:
          retval = self.runBash()
        else:
            if self.opts.output_dir:
                ste = open(self.elog,'w')
                sto = open(self.tlog,'w')
                sto.write('## Toolfactory generated command line = %s\n' % ' '.join(self.cl))
                sto.flush()
                p = subprocess.Popen(self.cl,shell=False,stdout=sto,stderr=ste,stdin=subprocess.PIPE,cwd=self.opts.output_dir)
            else:
                p = subprocess.Popen(self.cl,shell=False,stdin=subprocess.PIPE)
            p.stdin.write(self.script)
            p.stdin.close()
            retval = p.wait()
            if self.opts.output_dir:
                sto.close()
                ste.close()
                err = open(self.elog,'r').readlines()
                if retval <> 0 and err: # problem
                    print >> sys.stderr,err #same problem, need to capture docker stdin/stdout
            if self.opts.make_HTML:
                self.makeHtml()
        return retval

    def runBash(self):
        """
        cannot use - for bash so use self.sfile
        """
        if self.opts.output_dir:
            s = '## Toolfactory generated command line = %s\n' % ' '.join(self.cl)
            sto = open(self.tlog,'w')
            sto.write(s)
            sto.flush()
            p = subprocess.Popen(self.cl,shell=False,stdout=sto,stderr=sto,cwd=self.opts.output_dir)
        else:
            p = subprocess.Popen(self.cl,shell=False)            
        retval = p.wait()
        if self.opts.output_dir:
            sto.close()
        if self.opts.make_HTML:
            self.makeHtml()
        return retval
  

def main():
    u = """
    This is a Galaxy wrapper. It expects to be called by a special purpose tool.xml as:
    <command interpreter="python">rgBaseScriptWrapper.py --script_path "$scriptPath" --tool_name "foo" --interpreter "Rscript"
    </command>
    """
    op = argparse.ArgumentParser()
    a = op.add_argument
    a('--script_path',default=None)
    a('--tool_name',default=None)
    a('--interpreter',default=None)
    a('--output_dir',default='./')
    a('--output_html',default=None)
    a('--input_tab',default='None', nargs='*')
    a('--output_tab',default='None')
    a('--user_email',default='Unknown')
    a('--bad_user',default=None)
    a('--make_Tool',default=None)
    a('--make_HTML',default=None)
    a('--help_text',default=None)
    a('--tool_desc',default=None)
    a('--new_tool',default=None)
    a('--tool_version',default=None)
    a('--include_dependencies',default=None)
    a('--dockerized',default=0)
    a('--output_format', default='tabular')
    a('--input_format', dest='input_formats', action='append', default=[])
    a('--additional_parameters', dest='additional_parameters', action='append', default=[])
    opts = op.parse_args()
    assert not opts.bad_user,'UNAUTHORISED: %s is NOT authorized to use this tool until Galaxy admin adds %s to admin_users in universe_wsgi.ini' % (opts.bad_user,opts.bad_user)
    assert opts.tool_name,'## Tool Factory expects a tool name - eg --tool_name=DESeq'
    assert opts.interpreter,'## Tool Factory wrapper expects an interpreter - eg --interpreter=Rscript'
    assert os.path.isfile(opts.script_path),'## Tool Factory wrapper expects a script path - eg --script_path=foo.R'
    if opts.output_dir:
        try:
            os.makedirs(opts.output_dir)
        except:
            pass
    if opts.dockerized==0:
      switch_to_docker(opts)
      return
    r = ScriptRunner(opts)
    if opts.make_Tool:
        retcode = r.makeTooltar()
    else:
        retcode = r.run()
    os.unlink(r.sfile)
    if retcode:
        sys.exit(retcode) # indicate failure to job runner


if __name__ == "__main__":
    main()


